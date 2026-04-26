from langchain_core.messages import SystemMessage, AIMessage
from langchain_google_vertexai import ChatVertexAI
from core.state import AgentState
from core.models import ArchitectOutput
from core.memory import filter_architect_messages

def architect_node(state: AgentState) -> dict:
    """
    Węzeł Architekta wykorzystujący natywne Structured Outputs.
    Gwarantuje deterministyczny format WBS bez potrzeby parsowania Markdown.
    """
    llm = ChatVertexAI(
        model_name="gemini-3.1-pro-preview", # POPRAWIONE API ID DLA VERTEX AI
        temperature=0.2,
        location="global", # WYMAGANE DLA NOWYCH MODELI PREVIEW
        project="nifty-saga-493918-c8"
    )
    structured_llm = llm.with_structured_output(ArchitectOutput)
    
    filtered_messages = filter_architect_messages(state.get("messages", []))
    
    consultation_retries = state.get("consultation_retries", 0)
    current_phase = state.get("current_phase", "brainstorming")
    
    principles = state.get("guiding_principles", {"core_constitution": [], "project_directives": []})
    principles_text = f"ZASADY SYSTEMU: {principles.get('core_constitution')}\nDYREKTYWY PROJEKTU: {principles.get('project_directives')}"

    if current_phase == "execution" and consultation_retries < 2:
        # TRYB KONSULTACJI (DEBUGOWANIA)
        debug_prompt = SystemMessage(content=f"""Jesteś Principal AI Architectem w trybie interwencji krytycznej.
Koder utknął. Zawsze przestrzegaj tych zasad: {principles_text}.
Przeanalizuj historię wiadomości i błędy z testów. Zaproponuj konkretne, innowacyjne obejście problemu. Przekaż Koderowi dokładne instrukcje nowej implementacji.""")
        
        # Oczekujemy, że llm to ChatVertexAI zainicjalizowany jako gemini-3.1-pro
        response = llm.invoke([debug_prompt] + state.get("messages", []))
        
        return {
            "messages": [response],
            "consultation_retries": consultation_retries + 1,
            "retry_count": 0 # Twardy reset prób dla Kodera
        }
    else:
        # TRYB PLANOWANIA WBS (Twoja dotychczasowa logika, wzbogacona o zasady)
        planning_prompt = SystemMessage(content=f"""Jesteś AI Architectem. 
Twoje zasady: {principles_text}.
Przeanalizuj wymagania użytkownika i stwórz/zaktualizuj plan WBS.""")
        
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
            
        # ZACHOWAJ SWOJĄ LOGIKĘ: Tutaj użyj structured_llm do wygenerowania WBS
        response = structured_llm.invoke([planning_prompt] + filtered_messages)
        
        state_update = {"messages": [AIMessage(content="Zaktualizowałem plan WBS zgodnie z ustaleniami.")]}
        if response.wbs:
            state_update["wbs"] = response.wbs
            
        return state_update
