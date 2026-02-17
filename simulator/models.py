from enum import Enum
from typing import List, Optional, Union, Dict, Any, Callable
from pydantic import BaseModel, Field

# --- Action Definitions ---

class ActionType(str, Enum):
    RESPOND = "respond"       # Send text back to the agent
    END_TEST = "end_test"     # Terminate the simulation loop successfully
    FAIL_TEST = "fail_test"   # Forcefully fail the simulator run

class ReactorAction(BaseModel):
    type: ActionType
    payload: Optional[str] = None # The text to send (if RESPOND), or the failure reason (if FAIL_TEST)

# Pre-defined common actions for usability
class CommonActions:
    DONT_KNOW = ReactorAction(type=ActionType.RESPOND, payload="I don't know the answer to that. Please proceed with the information you have.")
    SUCCESS_END = ReactorAction(type=ActionType.END_TEST, payload="Test scenario completed successfully.")
    GIVE_UP_FAIL = ReactorAction(type=ActionType.FAIL_TEST, payload="Simulant chose to give up or got stuck.")

# --- Reactor Abstractions ---

class RegexReactor(BaseModel):
    """Reacts deterministically based on a regex match against the agent's turn text."""
    pattern: str
    action: ReactorAction
    
    # We add a hidden 'type' field to help Pydantic discriminate the union if we need to load from JSON
    reactor_type: str = Field(default="regex", exclude=True)

class LLMReactor(BaseModel):
    """Uses Gemini to decide if a condition is met, and optionally generate the response."""
    goal_prompt: str # e.g., "If the agent is asking for a file name, tell them the file is 'data.csv'."
    action: ReactorAction
    # The Engine evaluates the context against the goal_prompt to generate a dynamic RESPOND Action.
    # If the goal is not relevant to the agent's text, it is bypassed for the next reactor.
    
    reactor_type: str = Field(default="llm", exclude=True)

ReactorType = Union[RegexReactor, LLMReactor]

# --- Verification Models ---

class FileExpectation(BaseModel):
    path: str
    exists: bool = True
    contains_text: Optional[str] = None
    exact_content: Optional[str] = None

# --- Main Case Definition ---

class InteractiveSimulationCase(BaseModel):
    name: str = Field(..., description="Name of the test scenario")
    initial_prompt: str = Field(..., description="The very first message to send to the CLI")
    
    # Environment Setup
    setup_dir: Optional[str] = Field(None, description="Path to a directory containing files to seed into the workspace.")
    setup_files: Dict[str, str] = Field(default_factory=dict, description="Map of filename -> content to create before test begins.")
    
    # State Machine Rules
    reactors: List[ReactorType] = Field(
        default_factory=list, 
        description="Rules evaluated in order to determine the next action."
    )
    default_action: ReactorAction = Field(
        default=CommonActions.DONT_KNOW, 
        description="Fallback action if no reactor matches or the LLM refuses."
    )
    
    max_turns: int = 10
    
    # Typed Output Extraction
    output_schema: Optional[type[BaseModel]] = Field(None, description="Pydantic schema to guide and extract structured JSON output.")
    
    # Post-Execution Verification
    expected_files: List[FileExpectation] = Field(default_factory=list)
    custom_verify: Optional[Callable[[str, Any], bool]] = Field(None, exclude=True)

# --- Output DTOs ---

class SimulationTurn(BaseModel):
    turn_number: int
    user_prompt: str
    agent_response: str
    reactor_type_engaged: str
    reactor_payload: Optional[str] = None
    
class SimulationTranscript(BaseModel):
    case_name: str
    backend: str
    turns: List[SimulationTurn] = Field(default_factory=list)
    
class SimulationResult(BaseModel):
    case_name: str
    backend: str
    success: bool
    transcript: SimulationTranscript
    extracted_output: Optional[BaseModel] = None
    failed_file_verifications: List[str] = Field(default_factory=list, description="Paths of files that failed expectation checks")
    error_message: Optional[str] = None
