import random
import string
import time

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



app = FastAPI()
app.include_router(problems_router)

sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")
socket_app = socketio.ASGIApp(sio, app)

parties = {}
language_id = 100


# <----------------- Helper functions ----------------->

def get_random_problem(difficulty: list[bool], problem_id: int = None) -> dict:
    db = SessionLocal()

    try:
        problem = get_problem(db, difficulty, problem_id)
        return {"name": problem.problem_name, "description": problem.problem_description, "difficulty": problem.problem_difficulty, "test_cases": problem.test_cases, "function_signature": problem.function_signature, "any_order": problem.any_order, "reports": problem.reports}
    
    finally:
        db.close()


def generate_party_code() -> str:
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))


def all_players_passed(party_code: str) -> bool:
    for player in parties[party_code]["players"]:
        if not player["passed"]:
            return False
    return True


def reset_players_passed(party_code: str) -> None:
    for player in parties[party_code]["players"]:
        player["passed"] = False


async def game_timeout(party_code: str, time_limit: str, problem_name: str) -> None:
    await asyncio.sleep(int(time_limit) * 60)
    if party_code in parties and parties[party_code]["status"] == "in_progress" and problem_name == parties[party_code]["problem"]["name"]:
        parties[party_code]["status"] = "waiting"
        reset_players_passed(party_code)
        await sio.emit("announcement", {"message": "Time is up!"}, room=party_code)
        await asyncio.sleep(3)
        await sio.emit("game_over", room=party_code)


@limits(calls=20, period=5)
def rate_limiter() -> None:
    return

async def start_new_round(party_code: str) -> None:
    """Start a new round with a new problem and reset per-round variables."""
    party = parties[party_code]
    difficulty = party["difficulties"]
    time_limit = party["time_limit"]
    problem = get_random_problem(difficulty)
    party["problem"] = problem
    party["status"] = "in_progress"
    party["finish_count"] = 0
    end_time = time.time() + (time_limit * 60)
    party["end_time"] = end_time
    for player in party["players"]:
        player["passed"] = False
        player["finish_order"] = None
        player["current_score"] = 0
        player["code"] = f"{problem['function_signature']}:\n    # your code here\n    return"
        player["console_output"] = "Test case output"
    await sio.emit(
        "game_started",
        {
            "problem": problem,
            "party_code": party_code,
            "round": party["current_round"],
            "total_rounds": party["total_rounds"],
        },
        room=party_code,
    )
    await sio.emit("update_time", {"time_left": (time_limit * 60)}, to=party["host"])
    asyncio.create_task(game_timeout(party_code, time_limit, problem["name"]))

# <----------------- Socket events ----------------->

@sio.event
async def create_party(sid: str, data: dict) -> None:
    print(f"create_party event received from {sid}: {data}")
    party_code = generate_party_code()
    parties[party_code] = {
        "host": sid,
        "players": [
            {
                "sid": sid,
                "username": data["username"],
                "passed": False,
                "current_score": 0,
                "total_score": 0,
                "finish_order": None,
            }
        ],
        "problem": None,
        "status": "waiting",
    }
    await sio.emit("party_created", {"username": data["username"], "party_code": party_code}, to=sid)
    await sio.enter_room(sid, party_code)


@sio.event
async def join_party(sid: str, data: dict) -> None:
    print(f"join_party event received from {sid}: {data}")
    party_code = data["party_code"]
    username = data["username"]

    if party_code == "":
        if not parties:
            await sio.emit("error", {"message": "No parties to join"}, to=sid)
            return

        party_code = random.choice(list(parties.keys()))
        await sio.emit("set_party_code", {"party_code": party_code}, to=sid)

    if party_code not in parties:
        await sio.emit("error", {"message": "Party not found"}, to=sid)
        return

    if len(parties[party_code]["players"]) >= 10:
        await sio.emit("error", {"message": "Party is full!"}, to=sid)
        return
    
    if username in [d["username"] for d in parties[party_code]["players"]]:
        await sio.emit("error", {"message": "Username taken!"}, to=sid)
        return
    
    player = {
        "sid": sid,
        "username": username,
        "passed": False,
        "current_score": 0,
        "total_score": 0,
        "finish_order": None,
    }

    parties[party_code]["players"].append(player)
    player_usernames = [d["username"] for d in parties[party_code]["players"]]
    await sio.enter_room(sid, party_code)
    await sio.emit(
        "player_joined",
        {
            "username": username,
            "players": player_usernames,
        }, 
        room=party_code,
    )

    if parties[party_code]["status"] == "in_progress":
        problem = parties[party_code]["problem"]
        player["code"] = f"{problem['function_signature']}:\n    # your code here\n    return"
        player["console_output"] = "Test case output"
        await sio.emit("game_started", {"problem": parties[party_code]["problem"], "party_code": party_code, "round": parties[party_code].get('current_round', 1), "total_rounds": parties[party_code].get('total_rounds',1)}, to=sid)
        await sio.emit("announcement", {"message": f"{username} has joined the game!"}, room=party_code)


@sio.event
async def start_game(sid: str, data: dict, difficulties: list[bool] = []) -> None:
    print(f"start_game event received from {sid}: {data}")
    party_code = data["party_code"]
    difficulty = difficulties or [data["easy"], data["medium"], data["hard"]]
    time_limit = int(data["time_limit"] or "15")
    rounds = int(data.get("rounds", "1"))

    if party_code not in parties:
        await sio.emit("error", {"message": "Party not found"}, to=sid)
        return

    if parties[party_code]["host"] == sid:
        try:
            parties[party_code]["total_rounds"] = rounds
            parties[party_code]["current_round"] = 1
            parties[party_code]["finish_count"] = 0

            end_time = time.time() + (time_limit * 60)
            problem = get_random_problem(difficulty)
            parties[party_code]["problem"] = problem
            parties[party_code]["status"] = "in_progress"
            parties[party_code]["difficulties"] = difficulty
            parties[party_code]["time_limit"] = time_limit
            parties[party_code]["end_time"] = end_time

            for player in parties[party_code]["players"]:
                player["passed"] = False
                player["code"] = f"{problem['function_signature']}:\n    # your code here\n    return"
                player["console_output"] = "Test case output"
                player["current_score"] = 0
                player["total_score"] = 0
                player["finish_order"] = None

            await sio.emit(
                "game_started",
                {
                    "problem": problem,
                    "party_code": party_code,
                    "round": 1,
                    "total_rounds": rounds,
                },
                room=party_code,
            )
            await sio.emit("update_time", {"time_left": (time_limit * 60)}, to=sid)
            asyncio.create_task(game_timeout(party_code, time_limit, problem["name"]))

        except Exception as e:
            print(f"Error in start_game:\n{e}")
            await sio.emit("error", {"message": "An internal error occurred while retrieving problems."}, to=sid)

    else:
        await sio.emit("error", {"message": "You are not the host"}, to=sid)


@sio.event
async def submit_code(sid: str, data: dict) -> None:
    print(f"submit_code event received from {sid}: {data}")
    party_code = data["party_code"]

    if party_code not in parties:
        await sio.emit("leave_party", to=sid)
        return

    code = data["code"]
    problem_obj = parties[party_code]["problem"]
    problem = Problem(language_id, problem_obj)
    color = "#EF5350"

    r = problem.submit_code(code)

    if "message" in r:
        message_to_client = r["status"] + ", " + r["message"]
        message_to_room = data["username"] + " encountered an error."

    else:
        message_to_client = f"{r['status']}, {str(r['passed test cases'])}/{str(r['total test cases'])} test cases in {str(r['time'])}ms."
        message_to_room = f"{data['username']} passed {str(r['passed test cases'])}/{str(r['total test cases'])} test cases in {str(r['time'])}ms."
        if "failed_test" in r and r["failed_test"] is not None:
            message_to_client += "\n" + r["failed_test"] + (f" \nstdout: {r['stdout']}")

    if r["status"] == "Accepted":
        color = "#66BB6A"
        for player in parties[party_code]["players"]:
            if player["sid"] == sid:
                player["passed"] = True
                if player.get("finish_order") is None:
                    parties[party_code]["finish_count"] += 1
                    player["finish_order"] = parties[party_code]["finish_count"]
                try:
                    runtime = float(r["time"])
                except Exception:
                    runtime = 1
                if runtime == 0:
                    runtime = 1
                new_score = r["passed test cases"] / (runtime * player["finish_order"])
                if new_score > player.get("current_score", 0):
                    player["current_score"] = new_score
                await sio.emit("passed_all", to=sid)

    await sio.emit("code_submitted", {"message": message_to_client}, to=sid)

    if "message" not in r or r["message"] != "Rate limited! Please wait 5 seconds and try again.":
        await sio.emit("player_submit", {"message": message_to_room, "bold": True, "color": color}, room=party_code)

    if all_players_passed(party_code):
        party = parties[party_code]
        for player in party["players"]:
            player["total_score"] += player.get("current_score", 0)
        leaderboard = sorted(party["players"], key=lambda x: x["total_score"], reverse=True)
        await sio.emit(
            "round_leaderboard",
            {
                "leaderboard": [{"username": p["username"], "score": p["total_score"]} for p in leaderboard],
                "round": party["current_round"],
                "total_rounds": party["total_rounds"],
            },
            room=party_code,
        )
        if party["current_round"] < party["total_rounds"]:
            party["current_round"] += 1
            await asyncio.sleep(3)
            await start_new_round(party_code)
        else:
            await asyncio.sleep(3)
            await sio.emit(
                "final_leaderboard",
                {"leaderboard": [{"username": p["username"], "score": p["total_score"]} for p in leaderboard]},
                room=party_code,
            )
            await sio.emit("game_over", room=party_code)


@sio.event
async def player_opened(sid: str, data: dict) -> None:
    print(f"player_opened event received from {sid}: {data}")
    party_code = data["party_code"]
    if party_code not in parties:
        return
    
    if sid == parties[party_code]["host"]:
        await sio.emit("activate_settings", to=sid)

    player_usernames = [d["username"] for d in parties[party_code]["players"]]

    await sio.emit("players_update", {"players": player_usernames}, room=party_code)


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

    await sio.emit("message_received", {"username": username, "message": message}, room=party_code)


@sio.event
async def leave_party(sid: str, data: dict) -> None:
    print(f"leave_party event received from {sid}: {data}")
    party_code = data["party_code"]
    username = data["username"]
    await sio.emit("leave_party", to=sid)

    if party_code not in parties:
        return
    
    if parties[party_code]["status"] == "waiting":
        if parties[party_code]["host"] == sid:
            await sio.leave_room(sid, party_code)
            del parties[party_code]
        else:
            for player in parties[party_code]["players"]:
                if player["sid"] == sid:
                    parties[party_code]["players"].remove(player)
                    await sio.emit("player_left", {"username": username}, room=party_code)
                    await sio.leave_room(sid, party_code)
                    break
        
        return

    if parties[party_code]["host"] == sid:
        await sio.emit("announcement", {"message": "Host left the party."}, room=party_code)
        await asyncio.sleep(3)
        await sio.emit("leave_party", room=party_code)
        for player in parties[party_code]["players"]:
            await sio.leave_room(sid, party_code)

        del parties[party_code]

    else:
        for player in parties[party_code]["players"]:
            if player["sid"] == sid:
                parties[party_code]["players"].remove(player)
                await sio.emit("announcement", {"message": f"{username} has left the party."}, room=party_code)
                await sio.leave_room(sid, party_code)
                break

@sio.event
async def restart_game(sid: str, data: dict) -> None:
    party_code = data["party_code"]
    if party_code not in parties:
        await sio.emit("error", {"message": "Party not found"}, to=sid)
        return

    if parties[party_code]["host"] != sid:
        await sio.emit("error", {"message": "Only the host can restart the game."}, to=sid)
        return

    party = parties[party_code]
    party["current_round"] = 1
    party["finish_count"] = 0
    for player in party["players"]:
        player["total_score"] = 0
        player["current_score"] = 0
        player["finish_order"] = None
        player["passed"] = False

    config = {
        "party_code": party_code,
        "time_limit": party.get("time_limit", 15),
        "rounds": party.get("total_rounds", 1),
        "easy": party.get("difficulties", [True, True, True])[0],
        "medium": party.get("difficulties", [True, True, True])[1],
        "hard": party.get("difficulties", [True, True, True])[2],
    }
    await start_game(sid, config, party.get("difficulties", [True, True, True]))

@sio.event
async def disconnect(sid: str) -> None:
    print(f"disconnect event received from {sid}")
    for party_code, party in list(parties.items()):
        if party["host"] == sid or not party["players"]:
            await sio.leave_room(sid, party_code)
            await sio.emit("announcement", {"message": "Party deleted due to disconnect."}, room=party_code)
            await asyncio.sleep(2)
            await sio.emit("leave_party", room=party_code)
            if party_code in parties:
                del parties[party_code]

        for player in party["players"]:
            if player["sid"] == sid:
                await sio.emit("announcement", {"message": f"{player['username']} has left the party."}, room=party_code)
                await sio.emit("player_left", {"username": player["username"]}, room=party_code)
                party["players"].remove(player)
                await sio.leave_room(sid, party_code)
                break


@sio.event
async def skip_problem(sid: str, data: dict) -> None:
    party_code = data["party_code"]
    print(f"skip problem event received from {sid}, party code: {party_code}")
    if party_code not in parties:
        return
    
    party = parties[party_code]

    if party["host"] != sid:
        return
    
    await sio.emit("announcement", {"message": "Problem is being skipped..."}, room=party_code)
    await asyncio.sleep(1)

    for player in party["players"]:
        player["passed"] = False
        player["finish_order"] = None
        player["current_score"] = 0
    await start_game(sid, {"party_code": party_code, "time_limit": party["time_limit"], "easy": party["difficulties"][0], "medium": party["difficulties"][1], "hard": party["difficulties"][2], "rounds": party["total_rounds"]}, party["difficulties"])


@sio.event
async def retrieve_time(sid: str, data: dict) -> None:
    party_code = data["party_code"]
    if party_code not in parties:
        return
    
    time_left = parties[party_code]["end_time"] - time.time()
    print(f"retrieve_time event received from {sid}, time left: {time_left}")
    await sio.emit("update_time", {"time_left": time_left}, to=sid)


@sio.event
async def code_update(sid: str, data: dict) -> None:
    party_code = data["party_code"]
    new_code = data["code"]

    if party_code not in parties:
        return
    
    for player in parties[party_code]["players"]:
        if player["sid"] == sid:
            player["code"] = new_code

    await sio.emit("updated_code", {"message": new_code}, room=f"{sid}:spectate")


@sio.event
async def console_update(sid: str, data: dict) -> None:
    party_code = data["party_code"]
    new_text = data["console_output"]

    if party_code not in parties:
        return
    
    for player in parties[party_code]["players"]:
        if player["sid"] == sid:
            player["console_output"] = new_text

    await sio.emit("updated_console", {"message": new_text}, room=f"{sid}:spectate")


@sio.event
async def retrieve_players(sid: str, data: dict) -> None:
    party_code = data["party_code"]
    if party_code not in parties:
        return
    
    players = parties[party_code]["players"]
    player_usernames = [d["username"] for d in players]
    print(f"retrieve_players event received from {sid}, players: {player_usernames}")
    await sio.emit("send_players", {"players": player_usernames}, to=sid)


@sio.event
async def retrieve_code(sid: str, data: dict) -> None:
    print(f"retrieve_code event received from {sid}")
    party_code = data["party_code"]
    username = data["username"]
    spectate_sid = ""
    new_text = ""
    new_code = ""
    for player in parties[party_code]["players"]:
        if player["username"] == username:
            spectate_sid = player["sid"]
            new_text = player["console_output"]
            new_code = player["code"]
        else:
            await sio.leave_room(sid, f"{player['sid']}:spectate")
    if sid != spectate_sid:
        await sio.enter_room(sid, f"{spectate_sid}:spectate")

    await sio.emit("updated_console", {"message": new_text}, room=f"{spectate_sid}:spectate")
    await sio.emit("updated_code", {"message": new_code}, room=f"{spectate_sid}:spectate")


@sio.event
async def leave_spectate_rooms(sid: str, data: dict) -> None:
    party_code = data["party_code"]
    for player in parties[party_code]["players"]:
        await sio.leave_room(sid, f"{player['sid']}:spectate")


@sio.event
async def report_problem(sid: str, data: dict) -> None:
    print(f"Report problem event received from {sid}")
    party_code = data["party_code"]
    if party_code not in parties:
        return
    
    db = SessionLocal()
    try:
        increment_reports(db, parties[party_code]["problem"]["name"])
    finally:
        db.close()


@app.get("/")
async def read_root():
    return JSONResponse({"message": "Server is running"})


@app.get("/parties")
async def read_root_parties():
    return JSONResponse({"parties": parties})


if __name__ == "__main__":
    uvicorn.run("src.main:socket_app", host="0.0.0.0", port=port or 8000)