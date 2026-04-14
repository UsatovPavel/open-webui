"""
GPTHub / orchestrator internal API: emit message events without a user sk- API key.

Secured with GPTHUB_INTERNAL_EVENT_SECRET (shared with orchestrator via .env).
"""

import hmac
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from open_webui.env import GPTHUB_INTERNAL_EVENT_SECRET
from open_webui.internal.db import get_session
from open_webui.models.chats import Chats
from open_webui.socket.main import get_event_emitter

log = logging.getLogger(__name__)

router = APIRouter()


class GpthubEventForm(BaseModel):
    type: str
    data: dict


def _secret_ok(provided: str | None) -> bool:
    expected = (GPTHUB_INTERNAL_EVENT_SECRET or "").strip()
    if not expected:
        return False
    if provided is None:
        return False
    got = provided.strip()
    if len(got) != len(expected):
        return False
    try:
        return hmac.compare_digest(got.encode("utf-8"), expected.encode("utf-8"))
    except Exception:
        return False


@router.post('/chats/{chat_id}/messages/{message_id}/event', response_model=Optional[bool])
async def gpthub_internal_message_event(
    chat_id: str,
    message_id: str,
    form_data: GpthubEventForm,
    x_gpthub_internal_event_secret: str | None = Header(
        default=None,
        alias='X-GPTHub-Internal-Event-Secret',
    ),
    db: Session = Depends(get_session),
):
    if not (GPTHUB_INTERNAL_EVENT_SECRET or "").strip():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail='Not found',
        )

    if not _secret_ok(x_gpthub_internal_event_secret):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail='Invalid or missing internal event secret',
        )

    # Narrow surface: orchestrator only needs status updates.
    if form_data.type != 'status':
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='Only type "status" is allowed for this endpoint',
        )

    chat = Chats.get_chat_by_id(chat_id, db=db)
    if not chat:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail='Chat not found',
        )

    event_emitter = get_event_emitter(
        {
            'user_id': chat.user_id,
            'chat_id': chat_id,
            'message_id': message_id,
        }
    )

    try:
        if event_emitter:
            await event_emitter(form_data.model_dump())
        else:
            return False
        return True
    except Exception as e:
        log.warning('gpthub_internal_message_event failed: %s', e)
        return False
