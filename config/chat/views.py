from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.views.decorators.http import require_POST
import json

from .services import (
    procesar_consulta,
    reset_sesion,
    get_chat_history,
    _append_chat_message,
    clear_chat,
)
from .stt import build_stt_backend

from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required


def login_view(request):
    error = None
    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            return redirect("index")
        else:
            error = "Usuario o contraseña incorrectos."
    return render(request, "chat/login.html", {"error": error})


def logout_view(request):
    logout(request)
    return redirect("login")


@login_required(login_url="login")
def index_view(request):
    error = None

    if request.method == "POST":
        texto = request.POST.get("texto", "").strip()

        if texto.lower() in {"reset", "reiniciar"}:
            reset_sesion(request.session)
            request.session.modified = True
            return redirect("index")

        if texto:
            try:
                resultado = procesar_consulta(texto, request.session, request.user)

                _append_chat_message(request.session, "user", texto, "message")
                _append_chat_message(
                    request.session,
                    "assistant",
                    resultado.get("respuesta", ""),
                    resultado.get("tipo", "message"),
                )

                request.session.modified = True
            except Exception as e:
                error = f"Error inesperado: {str(e)}"

        return redirect("index")

    chat_history = get_chat_history(request.session)

    return render(request, "chat/index.html", {
        "error": error,
        "usuario": request.user,
        "chat_history": chat_history,
    })


@require_POST
@login_required(login_url="login")
def consulta_view(request):
    try:
        body = json.loads(request.body)
        texto = body.get("texto", "").strip()
    except (json.JSONDecodeError, KeyError):
        return JsonResponse({"error": "JSON inválido"}, status=400)

    if not texto:
        return JsonResponse({"error": "Texto vacío"}, status=400)

    if texto.lower() in {"reset", "reiniciar"}:
        reset_sesion(request.session)
        request.session.modified = True

        return JsonResponse({
            "tipo": "sistema",
            "respuesta": "Contexto borrado."
        })
    
    if texto.lower() == "vaciar_chat":
        clear_chat(request.session)
        request.session.modified = True
        return JsonResponse({
            "tipo": "sistema",
            "respuesta": "Chat vaciado."
    })

    try:
        resultado = procesar_consulta(
            texto,
            request.session,
            request.user
        )

        _append_chat_message(
            request.session,
            "user",
            texto,
            "message"
        )

        _append_chat_message(
            request.session,
            "assistant",
            resultado.get("respuesta", ""),
            resultado.get("tipo", "message")
        )

        request.session.modified = True

        return JsonResponse(resultado)

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


@login_required(login_url="login")
def examples_view(request):
    return render(request, "chat/examples.html", {
        "usuario": request.user,
    })


@require_POST
@login_required(login_url="login")
def speech_to_text_view(request):
    """
    Este endpoint solo transcribe el audio.
    NO llama al agente. La confirmación del texto transcrito se hace en frontend.
    """
    audio_file = request.FILES.get("audio")
    if not audio_file:
        return JsonResponse({"error": "No se recibió audio."}, status=400)

    audio_bytes = audio_file.read()
    mime_type = getattr(audio_file, "content_type", None)

    try:
        stt = build_stt_backend()
        texto_transcrito = stt.transcribe(audio_bytes, mime_type=mime_type)

        if not texto_transcrito:
            return JsonResponse(
                {"error": "No se pudo obtener texto del audio."},
                status=400,
            )

        return JsonResponse({
            "texto_transcrito": texto_transcrito,
        })
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)