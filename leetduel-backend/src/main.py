import random
import string
import time
import math
from dataclasses import asdict
from typing import List

import socketio
import asyncio
import uvicorn

from ratelimit import limits, RateLimitException
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from .submit import Problem
from .database import SessionLocal
from .crud import get_problem, increment_reports
from .config import port

from src.routes.problems import router as problems_router
from src.dataclass import *



app = FastAPI()
app.include_router(problems_router)

sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")
socket_app = socketio.ASGIApp(sio, app)

parties: dict[str, Party] = {}
language_id = 100


# <----------------- Helper functions ----------------->

def get_random_problem(difficulty: List[bool], problem_id: int | None = None) -> ProblemData | None:
    db = SessionLocal()

    try:
        problem = get_problem(db, difficulty, problem_id)
        if not problem:
            return None
        return problem.asdata()
    
    finally:
        db.close()


def generate_party_code() -> str:
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=6))


def all_players_passed(party_code: str) -> bool:
    return all([player.passed for player in parties[party_code].players.values()])


def reset_players_passed(party_code: str) -> None:
    for player in parties[party_code].players.values():
        player.passed = False


def get_score(submission: SubmissionData, finish_order: int = 10) -> float:
    return 100 * submission.passed_test_cases / (math.log10(max(2, float(submission.time))) * finish_order * submission.total_test_cases)


async def game_timeout(party_code: str, time_limit: int, problem_name: str) -> None:
    await asyncio.sleep(time_limit * 60)
    if party_code not in parties:
        return
    
    party = parties[party_code]

    if party.status == "in_progress" and party.problem != None and party.problem.name == problem_name:
        party.status = "waiting"
        reset_players_passed(party_code)

        message = MessageData("Time is up!", True, "")
        await sio.emit("message_received", asdict(message), room=party_code)
        await asyncio.sleep(3)
        await finish_round(party_code)


@limits(calls=20, period=5)
def rate_limiter() -> None:
    return

async def start_new_round(party_code: str) -> None:
    if party_code not in parties:
        return
    
    party = parties[party_code]
    difficulty = party.difficulties
    time_limit = party.time_limit

    problem = get_random_problem(difficulty)
    if not problem:
        return
    
    party.problem = problem
    party.status = "in_progress"
    party.finish_count = 0

    end_time = time.time() + (time_limit * 60)
    party.end_time = end_time

    for player in party.players.values():
        player.passed = False
        player.finish_order = None
        player.current_score = 0
        player.code = f"{problem.function_signature}:\n    # your code here\n    return"
        player.console_output = "Test case output"
    
    game_data = GameData(problem, party_code, time_limit, party.current_round, party.total_rounds)
    await sio.emit("game_started", asdict(game_data), room=party_code)
    time_data = TimeData(time_limit * 60)
    await sio.emit("update_time", asdict(time_data), to=party.host)
    asyncio.create_task(game_timeout(party_code, time_limit, problem.name))


async def finish_round(party_code: str) -> None:
    party = parties[party_code]
    party.status = "waiting"
    for player in party.players.values():
        player.total_score += player.current_score
    leaderboard_players = sorted(list(party.players.values()), key=lambda p: p.total_score, reverse=True)

    leaderboard = [Score(p.username, p.total_score) for p in leaderboard_players]
    leaderboard_data = LeaderboardData(leaderboard)

    if party.current_round < party.total_rounds:
        await sio.emit("round_leaderboard", asdict(leaderboard_data), room=party_code)
        party.current_round += 1

    else:
        await sio.emit("final_leaderboard", asdict(leaderboard_data), room=party_code)

# <----------------- Socket events ----------------->

@sio.event
async def create_party(sid: str, data: dict) -> None:
    print(f"create_party event received from {sid}: {data}")
    party_code = generate_party_code()
    player = Player(data["username"], False, "", "", 0, 0, None)
    party = Party(sid, {sid: player}, None, "waiting", 0, 0, 0, [True, True, True], 0, 0)
    parties[party_code] = party

    player_data = PlayerData(data["username"], party_code)
    await sio.emit("party_created", asdict(player_data), to=sid)
    await sio.enter_room(sid, party_code)


@sio.event
async def start_next_round(sid: str, data: dict) -> None:
    print(f"start_next_round event received from {sid}")
    party_code = data["party_code"]
    if party_code not in parties or sid != parties[party_code].host:
        message = MessageData("Only the host can start the next round!", True, "")
        await sio.emit("message_received", message, to=sid)
        return
    await start_new_round(party_code)


@sio.event
async def join_party(sid: str, data: dict) -> None:
    print(f"join_party event received from {sid}: {data}")
    party_code = data["party_code"]
    username = data["username"]

    if party_code == "":
        if not parties:
            e = TextData("No parties to join")
            await sio.emit("error", asdict(e), to=sid)
            return

        party_code = random.choice(list(parties.keys()))
        await sio.emit("set_party_code", {"party_code": party_code}, to=sid)

    if party_code not in parties:
        e = TextData("Party not found")
        await sio.emit("error", asdict(e), to=sid)
        return
    
    party = parties[party_code]

    if len(party.players) >= 10:
        e = TextData("Party is full!")
        await sio.emit("error", asdict(e), to=sid)
        return
    
    if username in [d.username for d in party.players.values()]:
        e = TextData("Username taken!")
        await sio.emit("error", asdict(e), to=sid)
        return
    
    player = Player(username, False, "", "", 0, 0, None)
    party.players[sid] = player
    player_usernames = [d.username for d in party.players.values()]

    await sio.enter_room(sid, party_code)
    player_data = PlayerData(username, party_code, player_usernames)

    await sio.emit("player_joined", asdict(player_data), room=party_code)

    if party.status == "in_progress":
        problem = party.problem
        if not problem:
            return
        
        player.code = f"{problem.function_signature}:\n    # your code here\n    return"
        player.console_output = "Test case output"
        game_data = GameData(problem, party_code, party.time_limit, party.current_round, party.total_rounds)

        await sio.emit("game_started", asdict(game_data), to=sid)
        
        message = MessageData(f"{username} has joined the game!", True, "")
        await sio.emit("message_received", asdict(message), room=party_code)


@sio.event
async def start_game(sid: str, data: dict, difficulties: List[bool] = []) -> None:
    print(f"start_game event received from {sid}: {data}")
    party_code = data["party_code"]
    difficulty = difficulties or [data["easy"], data["medium"], data["hard"]]
    time_limit = int(data["time_limit"] or "15")
    rounds = int(data["rounds"] or "1")

    if party_code not in parties:
        e = TextData("Party not found")
        await sio.emit("error", asdict(e), to=sid)
        return
    
    party = parties[party_code]

    if party.host != sid:
        e = TextData("You are not the host")
        await sio.emit("error", asdict(e), to=sid)
        return

    try:
        party.total_rounds = rounds
        party.current_round = 1
        party.finish_count = 0

        end_time = time.time() + (time_limit * 60)
        problem = get_random_problem(difficulty)

        if not problem:
            return
        
        party.problem = problem
        party.status = "in_progress"
        party.difficulties = difficulty
        party.time_limit = time_limit
        party.end_time = end_time

        for player in party.players.values():
            player.passed = False
            player.code = f"{problem.function_signature}:\n    # your code here\n    return"
            player.console_output = "Test case output"
            player.current_score = 0
            player.total_score = 0
            player.finish_order = None

        game_data = GameData(problem, party_code, time_limit,1, rounds)
        await sio.emit("game_started", asdict(game_data), room=party_code)

        time_data = TimeData(time_limit * 60)
        await sio.emit("update_time", asdict(time_data), to=sid)

        round_info = RoundInfo(1, rounds)
        await sio.emit("update_round_info", asdict(round_info), to=sid)
        asyncio.create_task(game_timeout(party_code, time_limit, problem.name))

    except Exception as e:
        print(f"Error in start_game:\n{e}")
        error = TextData("An internal error occurred while retrieving problems.")
        await sio.emit("error", asdict(error), to=sid)


@sio.event
async def submit_code(sid: str, data: dict) -> None:
    print(f"submit_code event received from {sid}")
    party_code = data["party_code"]

    if party_code not in parties:
        await sio.emit("leave_party", to=sid)
        return
    
    party = parties[party_code]
    if sid not in party.players.keys() or not party.problem:
        return
    
    player = party.players[sid]

    code = data["code"]
    problem_obj = party.problem
    problem = Problem(language_id, problem_obj)
    color = "#EF5350"

    submission = problem.submit_code(code)
    status = "Accepted" if submission.accepted else "Failed"
    
    if submission.message:
        message_to_client = f"{status}, {submission.message}stdout: {submission.stdout}"
        message_to_room = f"{data['username']} encountered an error."

    else:
        message_to_client = f"{status}, {str(submission.passed_test_cases)}/{str(submission.total_test_cases)} test cases in {submission.time}ms."
        message_to_room = f"{data['username']} passed {submission.passed_test_cases}/{str(submission.total_test_cases)} test cases in {submission.time}ms."
        if submission.failed_test != "":
            message_to_client += "\n" + submission.failed_test + (f" \nstdout: {submission.stdout}")
            score = get_score(submission)
            player.current_score = max(player.current_score, score)

    if submission.accepted:
        color = "#66BB6A"
        player.passed = True
        if player.finish_order is None:
            party.finish_count += 1
            player.finish_order = party.finish_count
        
        score = get_score(submission, player.finish_order)
        new_score = max(player.current_score, score)
        if new_score > player.current_score:
            player.current_score = new_score
        await sio.emit("passed_all", to=sid)

    client_message = TextData(message_to_client)
    await sio.emit("code_submitted", asdict(client_message), to=sid)

    if submission.message == None or submission.message != "Rate limited! Please wait 5 seconds and try again.":
        room_message = MessageData(message_to_room, True, color)
        await sio.emit("message_received", asdict(room_message), room=party_code)

    if all_players_passed(party_code):
        await finish_round(party_code)


@sio.event
async def player_opened(sid: str, data: dict) -> None:
    print(f"player_opened event received from {sid}: {data}")
    party_code = data["party_code"]
    if party_code not in parties:
        return
    
    party = parties[party_code]
    if sid == party.host:
        await sio.emit("activate_settings", to=sid)

    player_usernames = [d.username for d in party.players.values()]
    player_data = PlayerData("", party_code, player_usernames)

    await sio.emit("players_update", asdict(player_data), room=party_code)


@sio.event
async def chat_message(sid: str, data: dict) -> None:
    try:
        rate_limiter()
    except RateLimitException:
        return
    
    print(f"chat_message event received from {sid}: {data}")
    party_code = data["party_code"]
    message = data["message"]
    username = data["username"]

    message_data = MessageData(f"{username}: {message}", False, "")

    await sio.emit("message_received", asdict(message_data), room=party_code)


@sio.event
async def leave_party(sid: str, data: dict) -> None:
    print(f"leave_party event received from {sid}: {data}")
    party_code = data["party_code"]
    username = data["username"]
    await sio.emit("leave_party", to=sid)

    if party_code not in parties:
        return
    
    party = parties[party_code]
    if party.status == "waiting":
        if party.host == sid:
            await sio.leave_room(sid, party_code)
            del parties[party_code]
        else:
            del party.players[sid]
            player_data = PlayerData(username, party_code)
            await sio.emit("player_left", asdict(player_data), room=party_code)
            await sio.leave_room(sid, party_code)
        
        return

    if party.host == sid:
        message = MessageData("Host left the party.", True, "")
        await sio.emit("message_received", asdict(message), room=party_code)
        await asyncio.sleep(3)
        await sio.emit("leave_party", room=party_code)
        for player_sid in party.players:
            await sio.leave_room(player_sid, party_code)

        del parties[party_code]

    else:
        del party.players[sid]
        message = MessageData(f"{username} has left the party.", True, "")
        await sio.emit("message_received", asdict(message), room=party_code)
        await sio.leave_room(sid, party_code)
        

# @sio.event
# async def restart_game(sid: str, data: dict) -> None:
#     party_code = data["party_code"]
#     if party_code not in parties:
#         e = TextData("Party not found")
#         await sio.emit("error", asdict(e), to=sid)
#         return

#     party = parties[party_code]
#     if party.host != sid:
#         e = TextData("Only the host can restart the game.")
#         await sio.emit("error", asdict(e), to=sid)
#         return

#     party.current_round = 1
#     party.finish_count = 0
#     for player in party.players.values():
#         player.total_score = 0
#         player.current_score = 0
#         player.finish_order = None
#         player.passed = False

#     config = {
#         "party_code": party_code,
#         "time_limit": party.get("time_limit", 15),
#         "rounds": party.get("total_rounds", 1),
#         "easy": party.get("difficulties", [True, True, True])[0],
#         "medium": party.get("difficulties", [True, True, True])[1],
#         "hard": party.get("difficulties", [True, True, True])[2],
#     }
#     await start_game(sid, config, party.get("difficulties", [True, True, True]))


@sio.event
async def disconnect(sid: str) -> None:
    print(f"disconnect event received from {sid}")
    for party_code, party in list(parties.items()):
        if party.host == sid or not party.players:
            await sio.leave_room(sid, party_code)
            message = MessageData("Party deleted due to disconnect.", True, "")
            await sio.emit("message_received", asdict(message), room=party_code)

            await asyncio.sleep(2)
            await sio.emit("leave_party", room=party_code)
            if party_code in parties:
                del parties[party_code]

        if sid not in party.players:
            return

        player = party.players[sid]
        message = MessageData(f"{player.username} has left the party.", True, "")
        await sio.emit("message_received", asdict(message), room=party_code)
        await sio.emit("player_left", {"username": player.username}, room=party_code)

        del party.players[sid]
        await sio.leave_room(sid, party_code)


@sio.event
async def skip_problem(sid: str, data: dict) -> None:
    party_code = data["party_code"]
    print(f"skip problem event received from {sid}, party code: {party_code}")
    if party_code not in parties:
        return
    
    party = parties[party_code]

    if party.host != sid:
        message = MessageData("Only the host can skip problems!", True, "")
        await sio.emit("message_received", asdict(message), to=sid)
        return
    
    message = MessageData("Problem is being skipped...", True, "")
    await sio.emit("message_received", asdict(message), room=party_code)
    await asyncio.sleep(1)

    for player in party.players.values():
        player.passed = False
        player.finish_order = None
        player.current_score = 0

    await start_new_round(party_code)


@sio.event
async def retrieve_time(sid: str, data: dict) -> None:
    party_code = data["party_code"]
    if party_code not in parties:
        return
    
    party = parties[party_code]
    time_left = party.end_time - time.time()
    print(f"retrieve_time event received from {sid}, time left: {time_left}")
    time_data = TimeData(time_left)
    await sio.emit("update_time", asdict(time_data), to=sid)


@sio.event
async def retrieve_round_info(sid: str, data: dict) -> None:
    print(f"retrieve_round_info event received from {sid}")
    party_code = data["party_code"]
    if party_code not in parties:
        return

    party = parties[party_code]
    round_info = RoundInfo(party.current_round, party.total_rounds)
    await sio.emit("update_round_info", asdict(round_info), to=sid)


@sio.event
async def code_update(sid: str, data: dict) -> None:
    party_code = data["party_code"]
    new_code = data["code"]

    if party_code not in parties:
        return
    
    party = parties[party_code]
    party.players[sid].code = new_code
    code_data = TextData(new_code)

    await sio.emit("updated_code", asdict(code_data), room=f"{sid}:spectate")


@sio.event
async def console_update(sid: str, data: dict) -> None:
    party_code = data["party_code"]
    new_text = data["console_output"]

    if party_code not in parties:
        return
    
    party = parties[party_code]
    party.players[sid].console_output = new_text
    text_data = TextData(new_text)

    await sio.emit("updated_console", asdict(text_data), room=f"{sid}:spectate")


@sio.event
async def retrieve_players(sid: str, data: dict) -> None:
    party_code = data["party_code"]
    if party_code not in parties:
        return
    
    players = parties[party_code].players.values()
    player_usernames = [d.username for d in players]

    print(f"retrieve_players event received from {sid}, players: {player_usernames}")
    player_data = PlayerData("", party_code, player_usernames)
    await sio.emit("send_players", asdict(player_data), to=sid)


@sio.event
async def retrieve_code(sid: str, data: dict) -> None:
    print(f"retrieve_code event received from {sid}")
    party_code = data["party_code"]
    username = data["username"]
    spectate_sid = ""
    new_text = ""
    new_code = ""

    if party_code not in parties:
        return
    
    party = parties[party_code]
    for player_sid, player in party.players.items():
        if player.username == username:
            spectate_sid = player_sid
            new_text = player.console_output
            new_code = player.code
        else:
            await sio.leave_room(sid, f"{player_sid}:spectate")

    if sid != spectate_sid:
        await sio.enter_room(sid, f"{spectate_sid}:spectate")

    text_data = TextData(new_text)
    code_data = TextData(new_code)

    await sio.emit("updated_console", asdict(text_data), room=f"{spectate_sid}:spectate")
    await sio.emit("updated_code", asdict(code_data), room=f"{spectate_sid}:spectate")


@sio.event
async def leave_spectate_rooms(sid: str, data: dict) -> None:
    party_code = data["party_code"]
    for player_sid in parties[party_code].players:
        await sio.leave_room(sid, f"{player_sid}:spectate")


@sio.event
async def report_problem(sid: str, data: dict) -> None:
    print(f"Report problem event received from {sid}")
    party_code = data["party_code"]
    if party_code not in parties:
        return
    party = parties[party_code]
    db = SessionLocal()
    try:
        if party.problem:
            increment_reports(db, party.problem.name)
    finally:
        db.close()


@app.get("/")
async def read_root():
    return JSONResponse({"message": "Server is running"})



if __name__ == "__main__":
    uvicorn.run("src.main:socket_app", host="0.0.0.0", port=int(port))