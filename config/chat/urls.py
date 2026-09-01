from django.urls import path
from .views import (
    index_view,
    consulta_view,
    login_view,
    logout_view,
    speech_to_text_view,
    examples_view,
)

urlpatterns = [
    path("", index_view, name="index"),
    path("consulta/", consulta_view, name="consulta"),
    path("stt/", speech_to_text_view, name="speech_to_text"),
    path("login/", login_view, name="login"),
    path("logout/", logout_view, name="logout"),
    path("examples/", examples_view, name="examples"),
]
