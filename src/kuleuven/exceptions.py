class AuthenticationError(Exception):
    pass


class InvalidCredentialsError(AuthenticationError):
    pass


class SessionExpiredError(AuthenticationError):
    pass


class AuthApprovalTimeoutError(AuthenticationError):
    pass


class AuthApprovalFailedError(AuthenticationError):
    pass
