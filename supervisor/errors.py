"""Stable, non-secret supervisor error taxonomy."""


class SupervisorError(Exception):
    code = "supervisor_error"


class UnknownBotError(SupervisorError):
    code = "unknown_bot"


class BotDisabledError(SupervisorError):
    code = "disabled"


class BotAlreadyRunningError(SupervisorError):
    code = "already_running"


class BotAlreadyStoppedError(SupervisorError):
    code = "already_stopped"


class OperationInProgressError(SupervisorError):
    code = "operation_in_progress"


class ProcessStartError(SupervisorError):
    code = "startup_failed"


class ProcessIdentityError(SupervisorError):
    code = "process_identity"


class ShutdownTimeoutError(SupervisorError):
    code = "shutdown_timeout"


class SupervisorClosedError(SupervisorError):
    code = "supervisor_closed"
