"""
Application state definitions and legal transition table.
No business logic here — purely structural.
"""

from enum import Enum, auto
from PyQt6.QtCore import QObject, pyqtSignal


class AppState(Enum):
    SETUP    = auto()   # First-boot setup wizard
    SLEEP    = auto()   # Screen off, wake word detector running
    LISTENING = auto()  # Screen on, recording audio
    CONFIRMING = auto() # Showing confirmation screen for add/remove
    INVENTORY = auto()  # Showing inventory table


# Legal transitions: state -> set of states it may transition to
TRANSITIONS: dict[AppState, set[AppState]] = {
    AppState.SETUP:      {AppState.SLEEP},
    AppState.SLEEP:      {AppState.LISTENING},
    AppState.LISTENING:  {AppState.SLEEP, AppState.CONFIRMING, AppState.INVENTORY},
    AppState.CONFIRMING: {AppState.LISTENING, AppState.SLEEP},
    AppState.INVENTORY:  {AppState.SLEEP, AppState.LISTENING},
}


class StateMachine(QObject):
    """Emits state_changed whenever the app transitions to a new state."""

    state_changed = pyqtSignal(object)  # emits AppState value

    def __init__(self, initial: AppState = AppState.SETUP, parent=None):
        super().__init__(parent)
        self._state = initial

    @property
    def current(self) -> AppState:
        return self._state

    def transition(self, new_state: AppState) -> bool:
        """Attempt a transition. Returns True on success, False if illegal."""
        allowed = TRANSITIONS.get(self._state, set())
        if new_state not in allowed:
            return False
        self._state = new_state
        self.state_changed.emit(new_state)
        return True

    def force(self, new_state: AppState) -> None:
        """Transition without checking the table (for error recovery)."""
        self._state = new_state
        self.state_changed.emit(new_state)
