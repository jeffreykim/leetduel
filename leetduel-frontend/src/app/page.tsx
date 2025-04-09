"use client";
import React, { useState, useEffect, useRef, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import socket from "../socket";
import { useGame } from "../context/GameContext";
import { PlayerData, GameData, ErrorData } from "../types";
import Button from "./button";
import Color from "./colors";

enum PartyStatus {
  UNJOINED = "unjoined",
  JOINED = "joined",
  CREATED = "created",
}

function HomeContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { setProblem, setPartyCode, setUsername } = useGame();
  const [username, localSetUsername] = useState("");
  const [message, setMessage] = useState("");
  const [members, setMembers] = useState<string[]>([]);
  const [partyStatus, setPartyStatus] = useState<PartyStatus>(PartyStatus.UNJOINED);
  const [localPartyCode, setLocalPartyCode] = useState("");
  const [timeLimit, setTimeLimit] = useState("");
  const [rounds, setRounds] = useState("1");
  const [easy, setEasy] = useState(true);
  const [medium, setMedium] = useState(true);
  const [hard, setHard] = useState(true);
  const [showBanner, setShowBanner] = useState(false);
  const [goodBanner, setGoodBanner] = useState(true);

  const [createLoading, setCreateLoading] = useState(false);
  const [joinLoading, setJoinLoading] = useState(false);
  const [startLoading, setStartLoading] = useState(false);
  const [leaveLoading, setLeaveLoading] = useState(false);

  const [delayedMousePos, setDelayedMousePos] = useState({ x: 0, y: 0 });
  const mousePosRef = useRef({ x: 0, y: 0 });

  const handleMouseMove = (e: React.MouseEvent<HTMLDivElement>) => {
    mousePosRef.current = { x: e.clientX, y: e.clientY };
  };

  useEffect(() => {
    let animationFrameId: number;
    const updateDelayedPos = () => {
      setDelayedMousePos((prev) => ({
        x: prev.x + (mousePosRef.current.x - prev.x) * 0.05,
        y: prev.y + (mousePosRef.current.y - prev.y) * 0.05,
      }));
      animationFrameId = requestAnimationFrame(updateDelayedPos);
    };
    animationFrameId = requestAnimationFrame(updateDelayedPos);
    return () => cancelAnimationFrame(animationFrameId);
  }, []);

  useEffect(() => {
    const qpParty = searchParams.get("party");
    const qpUsername = searchParams.get("username");
    if (qpParty && partyStatus === PartyStatus.UNJOINED) {
      setLocalPartyCode(qpParty);
      setPartyCode(qpParty);
      setPartyStatus(PartyStatus.JOINED);
      if (qpUsername) {
        localSetUsername(qpUsername);
      }
    }
  }, [searchParams, setPartyCode]);

  useEffect(() => {
    socket.on("party_created", (data: PlayerData) => {
      if (!data.party_code) {
        setGoodBanner(false);
        setMessage("Party creation error");
        setCreateLoading(false);
        return;
      }
      setGoodBanner(true);
      setMessage(`Party created with code: ${data.party_code}`);
      setLocalPartyCode(data.party_code);
      setPartyCode(data.party_code);
      setPartyStatus(PartyStatus.CREATED);
      setUsername(username);
      setMembers([data.username]);
      setCreateLoading(false);
    });
    socket.on("players_update", (data: PlayerData) => {
      setMembers(data.players ? data.players : []);
    });
    socket.on("player_joined", (data: PlayerData) => {
      if (!data.players) {
        setGoodBanner(false);
        setMessage("Party join error");
        setJoinLoading(false);
        return;
      }
      setGoodBanner(true);
      setMessage(`${message}\n${data.username} joined`);
      setPartyStatus((prev) => (prev === PartyStatus.CREATED ? prev : PartyStatus.JOINED));
      setUsername(username);
      setMembers(data.players);
      setJoinLoading(false);
    });
    socket.on("player_left", (data: PlayerData) => {
      setMembers((prev) => prev.filter((member) => member !== data.username));
    });
    socket.on("game_started", (data: GameData) => {
      setGoodBanner(true);
      setProblem(data.problem);
      setPartyCode(data.party_code);
      router.push(`/game?party=${encodeURIComponent(data.party_code)}`);
    });
    socket.on("error", (data: ErrorData) => {
      setJoinLoading(false);
      setStartLoading(false);
      if (data.message === "Party not found") {
        setPartyStatus(PartyStatus.UNJOINED);
      }
      setGoodBanner(false);
      setMessage(`Error: ${data.message}`);
    });
    socket.on("activate_settings", () => {
      setPartyStatus(PartyStatus.CREATED);
    });
    socket.on("set_party_code", (data: GameData) => {
      setLocalPartyCode(data.party_code);
      setPartyCode(data.party_code);
    });
    return () => {
      socket.off("party_created");
      socket.off("players_update");
      socket.off("player_joined");
      socket.off("player_left");
      socket.off("game_started");
      socket.off("error");
      socket.off("activate_settings");
      socket.off("set_party_code");
    };
  }, [router, setProblem, setPartyCode, setUsername, username, message]);

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>;
    if (message) {
      setShowBanner(true);
      timer = setTimeout(() => setShowBanner(false), 3000);
    }
    return () => clearTimeout(timer);
  }, [message]);

  useEffect(() => {
    if (partyStatus) {
      console.log("Party status: ", partyStatus);
    }
  }, [partyStatus, setPartyStatus]);

  useEffect(() => {
    if (localPartyCode) {
      socket.emit("player_opened", { party_code: localPartyCode });
    }
  }, [localPartyCode]);

  const createParty = () => {
    if (username) {
      socket.emit("create_party", { username });
      return;
    }
    setCreateLoading(false);
  };

  const joinParty = () => {
    if (username) {
      socket.emit("join_party", { username, party_code: localPartyCode });
      return;
    }
    setJoinLoading(false);
  };

  const startGame = () => {
    if (isNaN(Number(timeLimit))) {
      setStartLoading(false);
      setGoodBanner(false);
      setMessage("Please enter a valid time limit.");
      return;
    }
    if (!rounds || isNaN(Number(rounds)) || Number(rounds) < 1) {
      setStartLoading(false);
      setGoodBanner(false);
      setMessage("Please enter a valid number of rounds.");
      return;
    }
    if (timeLimit && Number(timeLimit) < 1) {
      setStartLoading(false);
      setGoodBanner(false);
      setMessage("Time limit must be at least 1 minute.");
      return;
    }
    if (!easy && !medium && !hard) {
      setStartLoading(false);
      setGoodBanner(false);
      setMessage("Please select at least one difficulty level.");
      return;
    }
    if (localPartyCode) {
      setMessage(`Loading game...`);
      socket.emit("start_game", {
        party_code: localPartyCode,
        time_limit: timeLimit,
        rounds: rounds, // pass rounds setting to the server
        easy,
        medium,
        hard,
      });
    }
  };

  const leaveGame = () => {
    socket.emit("leave_party", { party_code: localPartyCode, username });
    localSetUsername("");
    setLocalPartyCode("");
    setPartyStatus(PartyStatus.UNJOINED);
    setPartyCode("");
    setUsername("");
    setMessage("");
    setLeaveLoading(false);
  };
  return (
    <div onMouseMove={handleMouseMove} className="page-wrapper">
      <div
        className="grid-background"
        style={
          {
            "--mouseX": delayedMousePos.x + "px",
            "--mouseY": delayedMousePos.y + "px",
          } as React.CSSProperties
        }
      />
      <div className="content-wrapper">
        <div className="min-h-screen flex items-center justify-center p-6 no-bg transition-colors relative">
          {message && (
            <div
              className="absolute top-0 left-0 w-full flex justify-center p-4"
              style={{
                opacity: showBanner ? 1 : 0,
                transition: "opacity 500ms ease",
              }}
            >
              <div
                className={`${
                  goodBanner
                    ? "bg-blue-200 text-blue-900"
                    : "bg-red-200 text-red-900"
                } p-3 rounded shadow-md relative max-w-xl w-full`}
              >
                <button
                  onClick={() => {
                    setShowBanner(false);
                    setMessage("");
                  }}
                  className="absolute top-2 right-2 text-blue-900 font-bold hover:text-blue-600 cursor-pointer"
                >
                  ✕
                </button>
                <p>{message}</p>
              </div>
            </div>
          )}
          <div className="bg-white dark:bg-gray-900 border-1 border-black dark:border-gray-300 transition duration-500 hover:border-green-400 shadow-lg rounded-xl p-8 w-full max-w-md font-inter">
            <h1 className="text-3xl text-gray-900 dark:text-white mb-6 text-center">
              Leetduel
            </h1>
            <div className="space-y-4 mb-6">
              <input
                type="text"
                placeholder="Username"
                value={username}
                onChange={(e) => localSetUsername(e.target.value)}
                disabled={partyStatus !== PartyStatus.UNJOINED}
                className="w-full px-4 py-3 rounded-lg bg-gray-200 dark:bg-gray-700 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500 transition"
              />
              <input
                type="text"
                placeholder="Party Code"
                value={localPartyCode}
                onChange={(e) => setLocalPartyCode(e.target.value)}
                disabled={partyStatus !== PartyStatus.UNJOINED}
                className="w-full px-4 py-3 rounded-lg bg-gray-200 dark:bg-gray-700 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500 transition"
              />
            </div>
            <div
              className="flex flex-col space-y-3 mb-6 transition-all duration-500 overflow-hidden"
              style={{
                maxHeight:
                  partyStatus === PartyStatus.UNJOINED ? "150px" : "0px",
                opacity: partyStatus === PartyStatus.UNJOINED ? 1 : 0,
              }}
            >
              <Button
                loading={createLoading}
                setLoading={setCreateLoading}
                handleClick={createParty}
                color={Color("green")}
              >
                Create Party
              </Button>
              <Button
                loading={joinLoading}
                setLoading={setJoinLoading}
                handleClick={joinParty}
                color={Color("blue")}
              >
                Join Party
              </Button>
            </div>
            <div
              className="transition-all space-y-3 duration-500 overflow-hidden mb-6"
              style={{
                maxHeight:
                  partyStatus !== PartyStatus.UNJOINED ? "500px" : "0px",
                opacity: partyStatus !== PartyStatus.UNJOINED ? 1 : 0,
              }}
            >
              <div className="mt-4 flex items-center space-x-6">
                <label className="flex items-center space-x-1">
                  <input
                    type="checkbox"
                    className="appearance-none w-5 h-5 border-2 border-gray-300 rounded-sm transition duration-300 checked:bg-blue-400 checked:border-transparent"
                    checked={easy}
                    onChange={(e) => setEasy(e.target.checked)}
                    disabled={partyStatus !== PartyStatus.CREATED}
                  />
                  <span className="text-gray-800 dark:text-gray-200">Easy</span>
                </label>
                <label className="flex items-center space-x-1">
                  <input
                    type="checkbox"
                    className="appearance-none w-5 h-5 border-2 border-gray-300 rounded-sm transition duration-300 checked:bg-green-400 checked:border-transparent"
                    checked={medium}
                    onChange={(e) => setMedium(e.target.checked)}
                    disabled={partyStatus !== PartyStatus.CREATED}
                  />
                  <span className="text-gray-800 dark:text-gray-200">
                    Medium
                  </span>
                </label>
                <label className="flex items-center space-x-1">
                  <input
                    type="checkbox"
                    className="appearance-none w-5 h-5 border-2 border-gray-300 rounded-sm transition duration-300 checked:bg-red-400 checked:border-transparent"
                    checked={hard}
                    onChange={(e) => setHard(e.target.checked)}
                    disabled={partyStatus !== PartyStatus.CREATED}
                  />
                  <span className="text-gray-800 dark:text-gray-200">Hard</span>
                </label>
              </div>
              <div className="mt-4">
                <input
                  type="number"
                  placeholder="Time limit (minutes)"
                  value={timeLimit}
                  onChange={(e) => setTimeLimit(e.target.value)}
                  disabled={partyStatus !== PartyStatus.CREATED}
                  className="w-full px-4 py-3 rounded-lg bg-gray-200 dark:bg-gray-700 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500 transition mb-3"
                />
              </div>
              <div className="mt-4">
                <input
                  type="number"
                  placeholder="Number of rounds"
                  value={rounds}
                  onChange={(e) => setRounds(e.target.value)}
                  disabled={partyStatus !== PartyStatus.CREATED}
                  className="w-full px-4 py-3 rounded-lg bg-gray-200 dark:bg-gray-700 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500 transition mb-3"
                />
              </div>
              <Button
                loading={startLoading}
                setLoading={setStartLoading}
                handleClick={startGame}
                color={Color("blue")}
              >
                Start Game
              </Button>
              <Button
                loading={leaveLoading}
                setLoading={setLeaveLoading}
                handleClick={leaveGame}
                color={Color("red")}
              >
                Leave Party
              </Button>
              <div className="mt-4">
                <h2 className="text-xl font-bold mb-2">Members</h2>
                <ul className="list-inside">
                  {members.map((member, idx) => (
                    <li key={idx} className="text-lg">
                      {member}
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          </div>
        </div>
      </div>
      <a
        href="https://github.com/jeffreykim/leetduel"
        target="_blank"
        rel="noopener noreferrer"
        className="github-logo"
      >
        <img src="/githublogo.png" alt="GitHub Logo" />
      </a>
      <style jsx global>{`
        .grid-background {
          position: fixed;
          top: 0;
          left: 0;
          width: 100vw;
          height: 100vh;
          pointer-events: none;
          z-index: 0;
        }
        .grid-background::before {
          content: "";
          position: absolute;
          inset: 0;
          background-image: repeating-linear-gradient(
              0deg,
              rgba(200, 200, 200, 0.15) 0,
              rgba(200, 200, 200, 0.15) 1px,
              transparent 1px,
              transparent 20px
            ),
            repeating-linear-gradient(
              90deg,
              rgba(200, 200, 200, 0.15) 0,
              rgba(200, 200, 200, 0.15) 1px,
              transparent 1px,
              transparent 20px
            );
          pointer-events: none;
        }
        .grid-background::after {
          content: "";
          position: absolute;
          inset: 0;
          background-image: repeating-linear-gradient(
              0deg,
              rgba(200, 200, 200, 0.15) 0,
              rgba(200, 200, 200, 0.15) 1px,
              transparent 1px,
              transparent 20px
            ),
            repeating-linear-gradient(
              90deg,
              rgba(200, 200, 200, 0.15) 0,
              rgba(200, 200, 200, 0.15) 1px,
              transparent 1px,
              transparent 20px
            );
          filter: brightness(1);
          -webkit-mask-image: radial-gradient(
            circle at var(--mouseX) var(--mouseY),
            white,
            transparent 1000px
          );
          mask-image: radial-gradient(
            circle at var(--mouseX) var(--mouseY),
            white,
            transparent 1000px
          );
          pointer-events: none;
        }
        .page-wrapper {
          position: relative;
          overflow: hidden;
        }
        .content-wrapper {
          position: relative;
          z-index: 1;
          background-color: transparent;
        }
        .no-bg {
          background: transparent !important;
        }
        /* New styles for GitHub logo */
        .github-logo {
          position: fixed;
          bottom: 10px;
          left: 10px;
          z-index: 2;
          transition: transform 0.3s, opacity 0.3s;
        }
        .github-logo img {
          width: 40px;
          height: 40px;
        }
        .github-logo:hover {
          transform: scale(1.1);
          opacity: 0.8;
        }
      `}</style>
    </div>
  );
}

export default function Home() {
  return (
    <Suspense fallback={<div>Loading...</div>}>
      <HomeContent />
    </Suspense>
  );
}