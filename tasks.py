# Define the tool definitions that will be shared between the tool-calling tasks.
# We use standard OpenAI function calling format.
# A dictionary (dict) is used here to represent each tool's name, description, and required parameters.
WEATHER_TOOL = {
    "type": "function",
    "function": {
        "name": "get_current_weather",
        "description": "Get the current weather for a location",
        "parameters": {
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "The city and state, e.g. San Francisco, CA"
                }
            },
            "required": ["location"]
        }
    }
}

STOCK_TOOL = {
    "type": "function",
    "function": {
        "name": "get_stock_price",
        "description": "Get the current stock price for a given ticker symbol",
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "The stock ticker symbol, e.g. NVDA"
                }
            },
            "required": ["symbol"]
        }
    }
}

# The main tasks list. This list of dicts serves as the static task battery.
# Each task has a unique id, a category, the prompt to send to the model,
# the string name of the grader function in grade.py, the expected ground truth value,
# and an optional list of tools if the task requires tool calling.
TASKS = [
    # --- Category 1: Coding (3 tasks) ---
    {
        "id": "coding_bug_fix",
        "category": "coding",
        "prompt": (
            "Fix the bug in the following Python function. The function should return the sum of all "
            "even numbers in a list, but it currently has a bug. Return ONLY the corrected Python "
            "code block inside standard markdown ```python ... ```. Do not include any other explanations.\n\n"
            "def sum_evens(nums):\n"
            "    total = 0\n"
            "    for n in nums:\n"
            "        if n % 2 == 1: # bug here\n"
            "            total += n\n"
            "    return total"
        ),
        "grader": "grade_code_execution",
        # We specify the function entry point and test inputs/expected outputs to verify code correctness.
        "expected": {
            "entry_point": "sum_evens",
            "test_cases": [
                {"args": [[1, 2, 3, 4]], "output": 6},
                {"args": [[]], "output": 0},
                {"args": [[1, 3, 5]], "output": 0}
            ]
        },
        "tools": None
    },
    {
        "id": "coding_from_scratch",
        "category": "coding",
        "prompt": (
            "Write a Python function `merge_sorted_lists(l1, l2)` that merges two sorted lists of "
            "integers and returns a single sorted list. Return ONLY the Python code block inside "
            "standard markdown ```python ... ```. Do not include any other explanations."
        ),
        "grader": "grade_code_execution",
        "expected": {
            "entry_point": "merge_sorted_lists",
            "test_cases": [
                {"args": [[1, 3, 5], [2, 4, 6]], "output": [1, 2, 3, 4, 5, 6]},
                {"args": [[], [1, 2]], "output": [1, 2]},
                {"args": [[1, 2], []], "output": [1, 2]},
                {"args": [[1, 1], [1, 1]], "output": [1, 1, 1, 1]}
            ]
        },
        "tools": None
    },
    {
        "id": "coding_review",
        "category": "coding",
        "prompt": (
            "Review the following Python code for any security vulnerabilities or critical bugs:\n\n"
            "def process_user_input(user_input):\n"
            "    # Execute user input directly in python\n"
            "    eval(user_input)\n\n"
            "Identify the specific critical security vulnerability in this code. Mention the name of the "
            "built-in function that makes it unsafe."
        ),
        "grader": "grade_substring",
        # If any of these substrings are present in the response (case-insensitive), it passes.
        "expected": ["eval", "arbitrary code execution", "remote code execution"],
        "tools": None
    },

    # --- Category 2: Math/Reasoning (3 tasks) ---
    {
        "id": "math_word_problem",
        "category": "math",
        "prompt": (
            "Solve the following word problem step by step, and output the final numeric answer as a single integer.\n\n"
            "A farmer has 15 apple trees. Each tree produces 40 apples. The farmer sells 250 apples and keeps "
            "50 apples for his family. He divides the remaining apples equally among 5 local food banks. "
            "How many apples does each food bank receive?"
        ),
        "grader": "grade_math",
        "expected": 60,
        "tools": None
    },
    {
        "id": "math_logic_puzzle",
        "category": "math",
        "prompt": (
            "Solve this logic puzzle and provide the final correct answer as a single integer.\n\n"
            "Five friends (Alice, Bob, Charlie, David, and Eva) are sitting in a row from left to right "
            "(positions 1 to 5).\n"
            "- Alice is not at either end.\n"
            "- Bob is sitting immediately to the right of Charlie.\n"
            "- David is at position 5.\n"
            "- Charlie is at position 2.\n\n"
            "What position is Eva sitting at?"
        ),
        "grader": "grade_math",
        "expected": 1,
        "tools": None
    },
    {
        "id": "math_derivation",
        "category": "math",
        "prompt": (
            "Consider the quadratic equation: x^2 - 14x + 45 = 0.\n"
            "Find the sum of the roots of this equation. Provide only the final numeric sum as a single integer."
        ),
        "grader": "grade_math",
        "expected": 14,
        "tools": None
    },

    # --- Category 3: Writing/Q&A (2 tasks) ---
    {
        "id": "writing_summarize",
        "category": "writing",
        "prompt": (
            "Summarize the following paragraph in one sentence:\n\n"
            "NVIDIA Corporation is an American multinational technology company incorporated in Delaware and "
            "based in Santa Clara, California. It is a software and fabless company which designs graphics "
            "processing units (GPUs), application programming interfaces (APIs) for data science and "
            "high-performance computing, as well as system on a chip units (SoCs) for the mobile computing "
            "and automotive market. NVIDIA is a global leader in artificial intelligence hardware and software, "
            "famously powering the modern AI revolution with its Hopper and Blackwell architecture chips.\n\n"
            "Make sure your summary contains the words 'multinational', 'graphics', and 'artificial'."
        ),
        "grader": "grade_writing_keywords",
        "expected": ["multinational", "graphics", "artificial"],
        "tools": None
    },
    {
        "id": "writing_format",
        "category": "writing",
        "prompt": (
            "Write a brief paragraph about the benefits of learning Python.\n"
            "You MUST follow these strict formatting rules:\n"
            "- The response must contain exactly 3 bullet points, each starting with a '*' character.\n"
            "- The total word count of the entire response must be under 50 words."
        ),
        "grader": "grade_writing_format",
        "expected": {
            "max_words": 50,
            "exact_bullets": 3,
            "bullet_char": "*"
        },
        "tools": None
    },

    # --- Category 4: Tool Calling (2 tasks) ---
    {
        "id": "tool_single",
        "category": "tool_calling",
        "prompt": "What is the weather like in New York? Use the available weather tool.",
        "grader": "grade_tool_call",
        "expected": {
            "required_calls": [
                {
                    "name": "get_current_weather",
                    # We check parameters loosely or specifically. Here we verify location contains 'new york' (case-insensitive).
                    "arguments": {"location": "New York"}
                }
            ]
        },
        "tools": [WEATHER_TOOL, STOCK_TOOL]
    },
    {
        "id": "tool_sequential",
        "category": "tool_calling",
        "prompt": "Check the stock price of NVDA and check the weather in San Francisco.",
        "grader": "grade_tool_call",
        "expected": {
            "required_calls": [
                {
                    "name": "get_stock_price",
                    "arguments": {"symbol": "NVDA"}
                },
                {
                    "name": "get_current_weather",
                    "arguments": {"location": "San Francisco"}
                }
            ]
        },
        "tools": [WEATHER_TOOL, STOCK_TOOL]
    }
]
