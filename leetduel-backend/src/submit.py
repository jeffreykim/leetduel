import json
import subprocess
import requests
import time
from ratelimit import limits, RateLimitException

from src.config import code_execution_url
from src.dataclass import ProblemData, SubmissionData
from src.config import judge0



class Problem:


    def __init__(self, language_id: int, problem: ProblemData):
        self.language_id = language_id
        self.problem = problem
        self.stdinput = json.dumps([test_case.input for test_case in problem.test_cases])
        self.api_key = judge0


    def submit_code(self, code: str, timeout: int = 10, code_timeout: int = 2) -> SubmissionData:
        function_name = self.problem.function_signature.split("(")[0][4:]
        code = """
import sys
import json
import time

class ListNode(object):
    def __init__(self, x=0, next=None):
        self.val = x
        self.next = next

    def __repr__(self):
        r = []
        copy = self
        while copy:
            r.append(copy.val)
            copy = copy.next

        return str(r)


def linkedList(a):
    if not a:
        return None
    
    head = curr = ListNode(a[0])
    for i in a[1:]:
        curr.next = ListNode(i)
        curr = curr.next

    return head
""" + f"""
{code}
input_data = sys.stdin.read().strip()
test_cases = json.loads(input_data)
start_time = time.time_ns()
results = []
for args in test_cases:
    print("|")
    results.append({function_name}(*eval(args)))

for result in results:
    print(result)
print(int((time.time_ns() - start_time) / 1e6))
        """

        try:
            result = self.run_judge0(code, timeout)

            if not result:
                return SubmissionData(False, "No response")

            if result["stderr"]:
                return SubmissionData(False, result["stderr"])
            
            return self.check_test_cases(result["stdout"], code_timeout)

        except subprocess.TimeoutExpired:
            return SubmissionData(False, "Time limit exceeded")
        
        except RateLimitException:
            return SubmissionData(False, "Rate limited! Please wait 5 seconds and try again.")
        
        except Exception as e:
            return SubmissionData(False, str(e))
        

    def check_test_cases(self, d: str, code_timeout: int) -> SubmissionData:
        test_cases = self.problem.test_cases
        any_order = self.problem.any_order

        if not d:
            return SubmissionData(False, "No output")

        data: list[str] = d.split("\n")[:-1]
        time: str = data.pop()

        if int(time) > code_timeout * 1000:
            return SubmissionData(False, "Time limit exceeded")

        count = 0
        failed_index = -1

        submission = SubmissionData(True, None, time, len(test_cases))
        r = {"status": "Accepted", "total test cases": len(test_cases), "time": time}

        n = len(test_cases)
        output = "\n".join(data[:-n])
        output_list = output.split("|\n")[1:]
        data = data[-n:]

        for i in range(len(data)):
            
            
            user_output = data[i]
            test_output = test_cases[i].output

            try:
                if any_order and isinstance(eval(user_output), list) and isinstance(eval(test_output), list):
                    user_output = eval(user_output)
                    test_output = eval(test_output)

                    user_output.sort()
                    test_output.sort()

            except Exception as e:
                print(e)

            if user_output != test_output:
                submission.accepted = False
                if failed_index == -1:
                    failed_index = i
                    submission.stdout = output_list[i]

                continue

            count += 1
        
        submission.passed_test_cases = count
        
        if failed_index != -1:
            submission.failed_test = f"Input: {str(eval(test_cases[failed_index].input))}\nExpected {test_cases[failed_index].output}, got {data[failed_index]}"

        return submission
    

    def run_naive(self, code: str, timeout: int) -> dict[str, str]:
        p = subprocess.run(
                ["python3", "-c", code],
                input=self.stdinput,
                capture_output=True,
                text=True,
                timeout=timeout
            )
        return {"stderr": p.stderr, "stdout": p.stdout}


    @limits(calls=5, period=10)
    def run_subprocess(self, code: str, timeout: int) -> dict[str, str]:
        if code_execution_url == "":
            return self.run_naive(code, timeout)
        
        response = requests.post(code_execution_url, json={"code": code, "timeout": timeout, "stdinput": self.stdinput})
        return response.json()
    
    
    def run_judge0(self, code: str, timeout: int) -> dict[str, str]:

        if judge0 == "":
            return self.run_naive(code, timeout)

        url = "https://judge0-ce.p.rapidapi.com/submissions/?base64_encoded=false&wait=false"
        headers = {
            "content-type": "application/json",
            "x-rapidapi-key": self.api_key,
            "x-rapidapi-host": "judge0-ce.p.rapidapi.com",
        }
        data = {
            "source_code": code,
            "language_id": self.language_id,
            "stdin": self.stdinput,
            "cpu_time_limit": 5,
            "wall_time_limit": 10,
        }
        response = requests.post(url, json=data, headers=headers)

        if response.status_code != 201:
            return {"stderr": "Internal error occurred", "stdout": ""}

        response_data = response.json()
        token = response_data["token"]
        description = "Processing"
        i = 0

        while description == "Processing":
            if i >= 3:
                return {"stderr": "Execution timed out", "stdout": ""}
            time.sleep(2)

            url = f"https://judge0-ce.p.rapidapi.com/submissions/{token}?base64_encoded=false"
            response = requests.get(url, headers=headers)

            if response.status_code != 200:
                return {"stderr": "Internal error occurred", "stdout": ""}
            
            response_data = response.json()
            description = response_data["status"]["description"]

            i += 1
        
        return {"stderr": response_data["stderr"], "stdout": response_data["stdout"]}