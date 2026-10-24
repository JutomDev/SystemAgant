from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from core.llm_factory import get_architect_llms
from core.memory import filter_architect_messages
from core.models import ArchitectOutput
from core.state import AgentState


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

    # Factory decouples execution mode (simulation vs live api)
    models = get_architect_llms()
    consultant_llm = models["consultant"]
    planner_llm = models["planner"]

    if current_phase == "execution" and consultation_retries < 3:
        # ====== CONSULTATION MODE (DEBUGGING) ======
        consultant_instruct = rf"""<role>You are a Principal AI Architect in critical intervention mode.</role>
<core_constitution>\n{principles.get("core_constitution")}\n</core_constitution>
<project_directives>\n{principles.get("project_directives")}\n</project_directives>
<instructions>The Coder is stuck. Analyze the message history and test errors. Propose a specific, innovative workaround. Provide the Coder with precise implementation instructions.
IMPORTANT: NEVER generate code blocks yourself. Do not write the code. Describe TO THE CODER what to change and WHY, but THEY must use the edit_file tool to apply changes. You are a strategist, not a programmer.
CRITICAL: You MUST output a detailed text response. NEVER output an empty message.</instructions>"""

        # System instruction as SystemMessage (guaranteed channel)
        consultant_sys_msg = SystemMessage(content=consultant_instruct)

        # Ensure at least one non-empty message exists (fixes Vertex AI error)
        if not filtered_messages:
            filtered_messages = [HumanMessage(content="Initialize architectural consultation.")]

        response = consultant_llm.invoke([consultant_sys_msg] + filtered_messages)

        return {
            "messages": [response],
            "consultation_retries": consultation_retries + 1,
            "retry_count": 0,  # Hard reset of retry counter for the Coder
        }
    else:
        # ====== WBS PLANNING MODE ======
        workspace_path = state.get("workspace_path", "")
        file_list = []
        ws_p = Path(workspace_path) if workspace_path else None
        if ws_p and ws_p.is_dir():
            try:
                # Discovers active source files while ignoring internal hidden files
                file_list = [p.name for p in ws_p.iterdir() if p.is_file() and not p.name.startswith(".")]
            except OSError:
                file_list = ["Error reading workspace"]

        planner_instruct = rf"""<role>You are an AI Architect responsible for planning the project structure.</role>
<core_constitution>\n{principles.get("core_constitution")}\n</core_constitution>
<project_directives>\n{principles.get("project_directives")}\n</project_directives>
<context>
The project folder ({workspace_path}) currently contains the following files: {file_list}
The Coder has access to these files via read_file and edit_file tools.
NEVER ask the user to paste code that is already on disk. Instead, plan a task for the Coder to analyze those files.
</context>
<instructions>Analyze user requirements and create/update the WBS plan.
Reply in the user's language explaining the technical strategy, but formulate all task IDs, file targets, and code references in English.
Generate a structured JSON object with a 'response' field (your text response to the user) and an optional 'wbs' field (list of Epics with tasks).</instructions>"""

        structured_planner = planner_llm.with_structured_output(ArchitectOutput)

        if current_phase == "brainstorming":
            brainstorm_prompt = SystemMessage(
                content=(
                    f"You are in the 'brainstorming' phase. Files available in workspace: {file_list}. "
                    "You are acting as a conversational partner and Technical Lead. "
                    "The user might be asking for advice, discussing architecture, or requesting changes to the plan. "
                    "1. Answer their questions directly and professionally. "
                    "2. DO NOT generate a WBS JSON object unless the user explicitly says 'Create the plan' or 'Generate WBS'. "
                    "3. If you are just answering a question, leave the 'wbs' field empty/null in your structured output and only provide the 'response' text."
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
        raw_wbs = response.wbs if hasattr(response, "wbs") else response.get("wbs", [])
        wbs_list = raw_wbs if raw_wbs is not None else []

        # Extract the Architect's text response
        main_response = response.response if hasattr(response, "response") else response.get("response", "")
        plan_text = f"{main_response}\n"

        if wbs_list:
            plan_text += "\nHere is the generated Work Breakdown Structure (WBS):\n"
            for i, epic in enumerate(wbs_list):
                # Handle both Pydantic objects and plain dictionaries
                if isinstance(epic, dict):
                    epic_name = epic.get("description", epic.get("epic_id", f"Epic {i + 1}"))
                    tasks = epic.get("tasks", [])
                else:
                    epic_name = getattr(epic, "description", getattr(epic, "epic_id", f"Epic {i + 1}"))
                    tasks = getattr(epic, "tasks", [])

                plan_text += f"\n🔹 **{epic_name}**\n"

                for task in tasks:
                    if isinstance(task, dict):
                        task_desc = task.get("description", "Task")
                    else:
                        task_desc = getattr(task, "description", "Task")
                    plan_text += f"   - {task_desc}\n"

            plan_text += "\nIf you approve this plan, type 'APPROVE' (or 'ZATWIERDZAM'), or provide your adjustments."

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

        return {"wbs": wbs_dicts, "messages": [AIMessage(content=plan_text)]}
