"""Dependencies for the owner-console routes: the data store and the call dispatcher.

Tests override these with `app.dependency_overrides`; C18 swaps the dispatcher by setting
`app.state.call_dispatcher` (or overriding `get_call_dispatcher`).
"""

from typing import Annotated

from fastapi import Depends, Request

from sg_api.admin.dispatcher import CallDispatcher, StubCallDispatcher
from sg_api.admin.sql_store import SqlAdminStore
from sg_api.admin.store import AdminStore
from sg_core.db import get_sessionmaker
from sg_core.settings import Settings, get_settings


def get_admin_store(request: Request) -> AdminStore:
    store: AdminStore | None = getattr(request.app.state, "admin_store", None)
    if store is None:
        store = SqlAdminStore(get_sessionmaker(), get_settings())
        request.app.state.admin_store = store
    return store


def get_call_dispatcher(request: Request) -> CallDispatcher:
    dispatcher: CallDispatcher | None = getattr(request.app.state, "call_dispatcher", None)
    if dispatcher is None:
        dispatcher = StubCallDispatcher()
        request.app.state.call_dispatcher = dispatcher
    return dispatcher


StoreDep = Annotated[AdminStore, Depends(get_admin_store)]
DispatcherDep = Annotated[CallDispatcher, Depends(get_call_dispatcher)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
