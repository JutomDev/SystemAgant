from langchain_core.messages import SystemMessage, AIMessage
from langchain_google_vertexai import ChatVertexAI
from core.state import AgentState
from core.models import ArchitectOutput
from core.memory import filter_architect_messages

def architect_node(state: AgentState) -> dict:
    """
    Węzeł Architekta wykorzystujący natywne Structured Outputs.
    Gwarantuje deterministyczny format WBS bez potrzeby parsowania Markdown.
    Używa dwóch osobnych modeli z natywną instrukcją systemową (system_instruction).
    """
    filtered_messages = filter_architect_messages(state.get("messages", []))
    
    consultation_retries = state.get("consultation_retries", 0)
    current_phase = state.get("current_phase", "brainstorming")
    
    principles = state.get("guiding_principles", {"core_constitution": [], "project_directives": []})

    # 1. Konsultant - do rozwiązywania problemów i iteracji
    consultant_llm = ChatVertexAI(
        model_name="gemini-3.1-pro-preview", 
        location="global", 
        project="nifty-saga-493918-c8",
        temperature=0.6,
        max_output_tokens=8192,
        model_kwargs={"thinking_level": "high"}
    )
    
    # 2. Planista - do tworzenia WBS i fazy Brainstormingu
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
        # ====== TRYB KONSULTACJI (DEBUGOWANIA) ======
        consultant_instruct = f"""<role>Jesteś Principal AI Architectem w trybie interwencji krytycznej.</role>
<core_constitution>\n{principles.get('core_constitution')}\n</core_constitution>
<project_directives>\n{principles.get('project_directives')}\n</project_directives>
<instructions>Koder utknął. Przeanalizuj historię wiadomości i błędy z testów. Zaproponuj konkretne, innowacyjne obejście problemu. Przekaż Koderowi dokładne instrukcje nowej implementacji.</instructions>"""

        # Instrukcja systemowa jako SystemMessage (gwarantowany kanał)
        consultant_sys_msg = SystemMessage(content=consultant_instruct)
        response = consultant_llm.invoke([consultant_sys_msg] + state.get("messages", []))
        
        return {
            "messages": [response],
            "consultation_retries": consultation_retries + 1,
            "retry_count": 0  # Twardy reset prób dla Kodera
        }
    else:
        # ====== TRYB PLANOWANIA WBS ======
        planner_instruct = f"""<role>Jesteś AI Architectem odpowiedzialnym za planowanie struktury projektu.</role>
<core_constitution>\n{principles.get('core_constitution')}\n</core_constitution>
<project_directives>\n{principles.get('project_directives')}\n</project_directives>
<instructions>Przeanalizuj wymagania użytkownika i stwórz/zaktualizuj plan WBS. Generuj ustrukturyzowany obiekt JSON z polem 'response' (Twoja tekstowa odpowiedź) oraz opcjonalnym polem 'wbs' (lista Epików z zadaniami).</instructions>"""
        
        structured_planner = planner_llm.with_structured_output(ArchitectOutput)
        
        if current_phase == "brainstorming":
            brainstorm_prompt = SystemMessage(
                content=(
                    "You are in the 'brainstorming' phase. Your primary goal is to discuss the project with the user. "
                    "Ask clarifying questions and refine the concept. "
                    "DO NOT generate a WBS until the user explicitly confirms they are ready to plan."
                )
            )
            filtered_messages.insert(0, brainstorm_prompt)
            
        wbs_context = state.get("wbs", [])
        if wbs_context:
            wbs_msg = SystemMessage(content=f"Current WBS Status: {wbs_context}")
            filtered_messages.insert(0, wbs_msg)
        
        # Instrukcja systemowa jako SystemMessage na początku listy
        planner_sys_msg = SystemMessage(content=planner_instruct)
        response = structured_planner.invoke([planner_sys_msg] + filtered_messages)
        
        # ODKNEBLOWANIE ARCHITEKTA: Renderowanie obiektu do tekstu
        raw_wbs = response.wbs if hasattr(response, 'wbs') else response.get("wbs", [])
        wbs_list = raw_wbs if raw_wbs is not None else []
        
        # Pobieramy tekstową odpowiedź architekta
        main_response = response.response if hasattr(response, 'response') else response.get("response", "")
        plan_text = f"{main_response}\n"

        if wbs_list:
            plan_text += "\nOto wygenerowany plan działania (WBS):\n"
            for i, epic in enumerate(wbs_list):
                # Obsługa zarówno obiektów Pydantic jak i zwykłych słowników
                if isinstance(epic, dict):
                    epic_name = epic.get('description', epic.get('epic_id', f'Epik {i+1}'))
                    tasks = epic.get('tasks', [])
                else:
                    epic_name = getattr(epic, 'description', getattr(epic, 'epic_id', f'Epik {i+1}'))
                    tasks = getattr(epic, 'tasks', [])

                plan_text += f"\n🔹 **{epic_name}**\n"
                
                for task in tasks:
                    if isinstance(task, dict):
                        task_desc = task.get('description', 'Zadanie')
                    else:
                        task_desc = getattr(task, 'description', 'Zadanie')
                    plan_text += f"   - {task_desc}\n"
                    
            plan_text += "\nJeśli akceptujesz ten plan, wpisz 'ZATWIERDZAM' (lub jeśli graf zapyta o zgodę, potwierdź), albo podaj swoje poprawki."

        # Konwersja obiektów Pydantic na słowniki przed zapisem do stanu
        # Zapobiega to błędom serializacji w SqliteSaver
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
