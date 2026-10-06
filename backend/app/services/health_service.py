"""Service that reports the health of the application and its dependencies."""

from app.schemas.health import HealthResponse


class HealthService:
    """Computes the health status of the service.

    Dependency checks (database, Redis) will be added once the infrastructure
    is in place.
    """

    async def check(self) -> HealthResponse:
        """Check the health of the service.

        Returns:
            The current health status.
        """
        return HealthResponse(status="ok")


def get_health_service() -> HealthService:
    """Provide a ``HealthService`` instance for dependency injection.

    Returns:
        A new ``HealthService``.
    """
    return HealthService()
