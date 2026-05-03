import os
from langchain_core.messages import SystemMessage, AIMessage
from langchain_google_vertexai import ChatVertexAI
from core.state import AgentState
from core.models import ArchitectOutput
from core.memory import filter_architect_messages

def architect_node(state: AgentState) -> dict:
    """
    Architect node leveraging native Structured Outputs.
    Guarantees deterministic WBS format without Markdown parsing.
    Uses two separate models with native system instructions.
    """
    filtered_messages = filter_architect_messages(state.get("messages", []))
    
    consultation_retries = state.get("consultation_retries", 0)
    current_phase = state.get("current_phase", "brainstorming")
    
    principles = state.get("guiding_principles", {"core_constitution": [], "project_directives": []})

    # 1. Consultant — for problem-solving and iteration
    consultant_llm = ChatVertexAI(
        model_name="gemini-3.1-pro-preview", 
        location="global", 
        project="nifty-saga-493918-c8",
        temperature=0.6,
        max_output_tokens=8192,
        model_kwargs={"thinking_level": "high"}
    )
    
    # 2. Planner — for WBS creation and Brainstorming phase
    planner_llm = ChatVertexAI(
        model_name="gemini-3.1-pro-preview", 
        location="global", 
        project="nifty-saga-493918-c8",
        temperature=0.4,
        top_p=0.95,
        presence_penalty=0.1,
        max_output_tokens=8192,
        model_kwargs={"thinking_level": "high"}
    )

    if current_phase == "execution" and consultation_retries < 2:
        # ====== CONSULTATION MODE (DEBUGGING) ======
        consultant_instruct = f"""<role>You are a Principal AI Architect in critical intervention mode.</role>
<core_constitution>\n{principles.get('core_constitution')}\n</core_constitution>
<project_directives>\n{principles.get('project_directives')}\n</project_directives>
<instructions>The Coder is stuck. Analyze the message history and test errors. Propose a specific, innovative workaround. Provide the Coder with precise implementation instructions.
IMPORTANT: NEVER generate code blocks yourself. Do not write the code. Describe TO THE CODER what to change and WHY, but THEY must use the edit_file tool to apply changes. You are a strategist, not a programmer.</instructions>"""

        # System instruction as SystemMessage (guaranteed channel)
        consultant_sys_msg = SystemMessage(content=consultant_instruct)
        response = consultant_llm.invoke([consultant_sys_msg] + filtered_messages)
        
        return {
            "messages": [response],
            "consultation_retries": consultation_retries + 1,
            "retry_count": 0  # Hard reset of retry counter for the Coder
        }
    else:
        # ====== WBS PLANNING MODE ======
        workspace_path = state.get("workspace_path", "")
        file_list = []
        if workspace_path and os.path.exists(workspace_path):
            try:
                file_list = [f for f in os.listdir(workspace_path) if os.path.isfile(os.path.join(workspace_path, f))]
            except Exception:
                file_list = ["Error reading workspace"]

        planner_instruct = f"""<role>You are an AI Architect responsible for planning the project structure.</role>
<core_constitution>\n{principles.get('core_constitution')}\n</core_constitution>
<project_directives>\n{principles.get('project_directives')}\n</project_directives>
<context>
The project folder ({workspace_path}) currently contains the following files: {file_list}
The Coder has access to these files via read_file and edit_file tools.
NEVER ask the user to paste code that is already on disk. Instead, plan a task for the Coder to analyze those files.
</context>
<instructions>Analyze user requirements and create/update the WBS plan. Generate a structured JSON object with a 'response' field (your text response to the user) and an optional 'wbs' field (list of Epics with tasks).</instructions>"""
        
        structured_planner = planner_llm.with_structured_output(ArchitectOutput)
        
        if current_phase == "brainstorming":
            brainstorm_prompt = SystemMessage(
                content=(
                    f"You are in the 'brainstorming' phase. Files available in workspace: {file_list}. "
                    "You KNOW these files exist. You can acknowledge them. "
                    "DO NOT ask the user to paste code from these files. "
                    "Ask clarifying questions and refine the concept. "
                    "DO NOT generate a WBS until the user explicitly confirms they are ready to plan."
                )
            )
            filtered_messages.insert(0, brainstorm_prompt)
            
        wbs_context = state.get("wbs", [])
        if wbs_context:
            wbs_msg = SystemMessage(content=f"Current WBS Status: {wbs_context}")
            filtered_messages.insert(0, wbs_msg)
        
        # System instruction as SystemMessage at the beginning of the list
        planner_sys_msg = SystemMessage(content=planner_instruct)
        response = structured_planner.invoke([planner_sys_msg] + filtered_messages)
        
        # UNBLOCK ARCHITECT: Render structured object to text
        raw_wbs = response.wbs if hasattr(response, 'wbs') else response.get("wbs", [])
        wbs_list = raw_wbs if raw_wbs is not None else []
        
        # Extract the Architect's text response
        main_response = response.response if hasattr(response, 'response') else response.get("response", "")
        plan_text = f"{main_response}\n"

        if wbs_list:
            plan_text += "\nHere is the generated Work Breakdown Structure (WBS):\n"
            for i, epic in enumerate(wbs_list):
                # Handle both Pydantic objects and plain dictionaries
                if isinstance(epic, dict):
                    epic_name = epic.get('description', epic.get('epic_id', f'Epic {i+1}'))
                    tasks = epic.get('tasks', [])
                else:
                    epic_name = getattr(epic, 'description', getattr(epic, 'epic_id', f'Epic {i+1}'))
                    tasks = getattr(epic, 'tasks', [])

                plan_text += f"\n🔹 **{epic_name}**\n"
                
                for task in tasks:
                    if isinstance(task, dict):
                        task_desc = task.get('description', 'Task')
                    else:
                        task_desc = getattr(task, 'description', 'Task')
                    plan_text += f"   - {task_desc}\n"
                    
            plan_text += "\nJeśli akceptujesz ten plan, wpisz 'ZATWIERDZAM' (lub jeśli graf zapyta o zgodę, potwierdź), albo podaj swoje poprawki."

        # Convert Pydantic objects to dicts before saving to state
        # Prevents serialization errors in SqliteSaver
        wbs_dicts = []
        for epic in wbs_list:
            if hasattr(epic, "dict"):
                wbs_dicts.append(epic.dict())
            elif hasattr(epic, "model_dump"):
                wbs_dicts.append(epic.model_dump())
            else:
                wbs_dicts.append(epic)

        return {
            "wbs": wbs_dicts,
            "messages": [AIMessage(content=plan_text)]
        }
