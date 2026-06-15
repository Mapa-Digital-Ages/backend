"""Decorator to handle errors in FastAPI routes."""

import inspect
from functools import wraps

import jwt
from botocore.exceptions import ClientError, EndpointConnectionError, NoCredentialsError
from fastapi import HTTPException, status
from pydantic import ValidationError
from sqlalchemy.exc import (
    DataError,
    DisconnectionError,
    IntegrityError,
    InterfaceError,
    NoResultFound,
    OperationalError,
    SQLAlchemyError,
)

from md_backend.utils.logger import get_logger

logger_extra = {"component.name": "ErrorHandler", "component.version": "v1"}
logger = get_logger(__name__)


def handle_errors(func):
    """Decorator to handle errors in FastAPI routes."""

    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            res = func(*args, **kwargs)

            if inspect.isawaitable(res):
                return await res
            else:
                return res

        except HTTPException as e:
            logger.error(str(e), extra=logger_extra)
            raise e
        except ValidationError as e:
            logger.exception("Validation error: %s", e, extra=logger_extra)
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Request validation failed",
            ) from e
        except ValueError as e:
            logger.exception("Value error: %s", str(e), exc_info=e, extra=logger_extra)
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
        except jwt.ExpiredSignatureError as e:
            logger.exception("Token expired: %s", str(e), exc_info=e, extra=logger_extra)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired"
            ) from e
        except jwt.InvalidTokenError as e:
            logger.exception("Invalid token: %s", str(e), exc_info=e, extra=logger_extra)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
            ) from e
        except jwt.PyJWTError as e:
            logger.exception("JWT error: %s", str(e), exc_info=e, extra=logger_extra)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
            ) from e
        except IntegrityError as e:
            logger.exception("Integrity error: %s", str(e), exc_info=e, extra=logger_extra)
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="Conflict: integrity violation"
            ) from e
        except NoResultFound as e:
            logger.exception("No result found: %s", str(e), exc_info=e, extra=logger_extra)
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found"
            ) from e
        except DataError as e:
            logger.exception("Data error: %s", str(e), exc_info=e, extra=logger_extra)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid data"
            ) from e
        except (OperationalError, InterfaceError, DisconnectionError) as e:
            logger.exception("Database unavailable: %s", str(e), exc_info=e, extra=logger_extra)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database unavailable"
            ) from e
        except SQLAlchemyError as e:
            logger.exception("Database error: %s", str(e), exc_info=e, extra=logger_extra)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Database error"
            ) from e
        except NoCredentialsError as e:
            logger.exception(
                "Storage credentials missing: %s", str(e), exc_info=e, extra=logger_extra
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Storage credentials missing",
            ) from e
        except EndpointConnectionError as e:
            logger.exception("Storage unavailable: %s", str(e), exc_info=e, extra=logger_extra)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Storage unavailable"
            ) from e
        except ClientError as e:
            logger.exception("Storage error: %s", str(e), exc_info=e, extra=logger_extra)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY, detail="Storage error"
            ) from e
        except Exception as e:
            logger.exception(
                "An unexpected error occurred: %s", str(e), exc_info=e, extra=logger_extra
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="An internal error occurred",
            ) from e

    return wrapper
