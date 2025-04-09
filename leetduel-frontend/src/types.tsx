export type TestCase = {
  input: string;
  output: string;
};

export type Problem = {
  name: string;
  description: string;
  function_signature: string;
  difficulty: string;
  test_cases: TestCase[];
} | null;

export type GameContextType = {
  problem: Problem;
  setProblem: (problem: Problem) => void;
  partyCode: string;
  setPartyCode: (code: string) => void;
  username: string;
  setUsername: (username: string) => void;
};

export interface PlayerData {
  username: string;
  party_code?: string;
  players?: string[];
}

export interface GameData {
  problem: Problem;
  party_code: string;
  time_limit: string;
  round?: number;
  total_rounds?: number;
}

export interface ErrorData {
  message: string;
}

export interface MessageData {
  message: string;
  bold: boolean;
  color: string;
  username?: string;
}

export interface TimeData {
  time_left: number;
}
