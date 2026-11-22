"""Public SMTP email-code authentication endpoints."""
from fastapi import APIRouter, Request, Response, Depends, Header
from typing import Literal
from pydantic import BaseModel, Field

from app.services import email_auth
from app.services.auth import current_user

router = APIRouter()


class EmailCodeRequest(BaseModel):
    email: str = Field(min_length=1, max_length=320)


class EmailLoginRequest(EmailCodeRequest):
    code: str = Field(pattern=r'^[0-9]{6}$')
    invitation_code: str | None = Field(default=None, max_length=32)


def _ip(request):
    """Use the ASGI peer address; forwarded headers are not read by this router."""
    return request.client.host if request.client else 'unknown'


@router.get('/api/auth/email/settings')
def settings(response: Response):
    response.headers['Cache-Control'] = 'no-store'
    return email_auth.settings()


@router.post('/api/auth/email/code')
def send_code(payload: EmailCodeRequest, request: Request, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    return email_auth.send_code(payload.email, _ip(request))


@router.post('/api/auth/email/login')
def login(payload: EmailLoginRequest, request: Request, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    return email_auth.login(payload.email, payload.code, _ip(request), payload.invitation_code)


class SecurityCodeRequest(BaseModel):
    purpose: Literal['password', 'delete']


@router.post('/api/profile/email/code')
def send_rebind_code(payload: EmailCodeRequest, request: Request, response: Response, user=Depends(current_user)):
    response.headers['Cache-Control'] = 'no-store'
    return email_auth.send_rebind_code(user['id'], payload.email, _ip(request))


@router.post('/api/profile/email')
def rebind_email(payload: EmailLoginRequest, response: Response, authorization: str = Header(), user=Depends(current_user)):
    response.headers['Cache-Control'] = 'no-store'
    return email_auth.rebind_email(user['id'], payload.email, payload.code, authorization[7:])


@router.post('/api/profile/security/code')
def send_security_code(payload: SecurityCodeRequest, request: Request, response: Response, user=Depends(current_user)):
    response.headers['Cache-Control'] = 'no-store'
    return email_auth.send_account_code(user['id'], payload.purpose, _ip(request))
