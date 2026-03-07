CODER_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_hs_nodes",
            "description": "Searches the HS Database using Semantic Vector Retrieval. Use this INSTEAD of navigating trees. Pass a descriptive query (e.g., 'electronic smartwatch bluetooth') to get the top 5 most relevant HS subheadings.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "A semantic description of the item focusing on Material and Function."
                    },
                    "chapter_id": {
                        "type": "string",
                        "description": "Optional: Restrict search to a specific 2-digit chapter (e.g., '85'). If empty, searches globally."
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "query_legal_notes",
            "description": "Semantically searches legal rules (Section and Chapter notes) to find EXCLUSIONS and inclusions pertinent to your query to ensure legal compliance.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The item description or key features (e.g., 'smartwatch', 'live breeding horse')."
                    },
                    "section_id": {
                        "type": "string",
                        "description": "The Section ID (e.g., 'SECTION_XVI') mapped to the chapter."
                    },
                    "chapter_id": {
                        "type": "string",
                        "description": "The 2-digit Chapter ID (e.g., '85')."
                    }
                },
                "required": ["query", "section_id", "chapter_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "ask_user_clarification",
            "description": "If the item description lacks critical technical details REQUIRED to answer the '3 Golden Questions' (Material, Function/Purpose, Specific Characteristics) to choose between distinct nodes, use this tool to ask the user a specific question. You MUST provide a list of likely options based on Chapter Notes/Headings for the user to choose from.",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The specific question to ask the user."
                    },
                    "options": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "A list of at least 2 distinct multiple-choice options for the user based on the Heading/Subheading requirements. E.g., ['To be used for breeding', 'Other']."
                    }
                },
                "required": ["question", "options"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_general_rules",
            "description": "Retrieves the text of the General Interpretative Rules (GIRs). Useful when dealing with incomplete/unassembled goods, mixtures, or packaging.",
            "parameters": {
                "type": "object",
                "properties": {
                    "rule_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of specific rules to fetch, e.g., ['GIR_2a', 'GIR_2b']. If empty, returns all."
                    }
                }
            }
        }
    }
]
