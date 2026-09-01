(function () {
    "use strict";

    // URLs desde el script tag
    const scriptTag = document.currentScript;
    const URL_CONSULTA = scriptTag.dataset.urlConsulta;
    const URL_SPEECH_TO_TEXT = scriptTag.dataset.urlSpeechToText;
    const URL_EXAMPLES = scriptTag.dataset.urlExamples;

    let mediaRecorder = null;
    let audioChunks = [];
    let activeStream = null;
    let textoPendienteConfirmacion = "";

    // DOM references
    const btnGrabar = document.getElementById("btnGrabar");
    const btnConfirmarTexto = document.getElementById("btnConfirmarTexto");
    const btnCancelarTexto = document.getElementById("btnCancelarTexto");
    const estadoGrabacion = document.getElementById("estadoGrabacion");
    const bloqueVoz = document.getElementById("bloqueVoz");
    const textoTranscrito = document.getElementById("textoTranscrito");
    const textoInput = document.getElementById("textoInput");
    const chatHistory = document.getElementById("chatHistory");
    const formTexto = document.getElementById("formTexto");
    const btnEnviarTexto = document.getElementById("btnEnviarTexto");
    const chatWrapper = document.getElementById("chatWrapper");
    const btnScrollAbajo = document.getElementById("btnScrollAbajo");
    const inputWrapper = document.getElementById("inputWrapper");
    const grabandoHint = document.getElementById("grabandoHint");

    // ============================================================
    //  AJUSTE DE ALTURA DINÁMICA PARA TECLADO EN iOS
    // ============================================================
    function actualizarAltoViewport() {
        const alto = window.visualViewport ? window.visualViewport.height : window.innerHeight;
        document.documentElement.style.setProperty('--app-height', `${alto}px`);
    }

    if (window.visualViewport) {
        window.visualViewport.addEventListener('resize', actualizarAltoViewport);
    } else {
        window.addEventListener('resize', actualizarAltoViewport);
    }
    window.addEventListener('orientationchange', actualizarAltoViewport);
    actualizarAltoViewport();

    // Al enfocar el input, forzar actualización y scroll al final
    textoInput.addEventListener('focus', function() {
        setTimeout(actualizarAltoViewport, 100);
        setTimeout(() => {
            if (chatWrapper) chatWrapper.scrollTop = chatWrapper.scrollHeight;
        }, 350);
    });
    textoInput.addEventListener('blur', function() {
        setTimeout(actualizarAltoViewport, 100);
    });

    // ============================================================
    //  FUNCIONES AUXILIARES
    // ============================================================
    function getCsrfToken() {
        const cookie = document.cookie
            .split("; ")
            .find(row => row.startsWith("csrftoken="));
        return cookie ? cookie.split("=")[1] : "";
    }

    function stopTracks() {
        if (activeStream) {
            activeStream.getTracks().forEach(track => track.stop());
            activeStream = null;
        }
    }

    let estadoGrabacionTimeoutId = null;

    function mostrarEstadoGrabacion(texto, autoOcultarMs) {
        // Cancela cualquier auto-ocultado pendiente de un mensaje anterior,
        // para que no borre por sorpresa un mensaje más reciente.
        if (estadoGrabacionTimeoutId) {
            clearTimeout(estadoGrabacionTimeoutId);
            estadoGrabacionTimeoutId = null;
        }

        estadoGrabacion.textContent = texto;
        if (texto) {
            estadoGrabacion.classList.add("visible");
        } else {
            estadoGrabacion.classList.remove("visible");
        }

        if (texto && autoOcultarMs) {
            estadoGrabacionTimeoutId = setTimeout(() => {
                mostrarEstadoGrabacion("");
            }, autoOcultarMs);
        }
    }

    function resetVoiceBlock() {
        textoPendienteConfirmacion = "";
        textoTranscrito.textContent = "";
        btnConfirmarTexto.classList.add("hidden");
        btnCancelarTexto.classList.add("hidden");
    }

    function addChatBubble(role, kind, content) {
        if (!content) return;

        const wrapper = document.createElement("div");
        wrapper.className = `chat-msg chat-msg-${role} chat-kind-${kind} chat-msg-enter`;

        const bubble = document.createElement("div");
        bubble.className = "chat-bubble";

        const small = document.createElement("small");
        small.textContent = role === "user" ? "Tú" : "Sistema";

        const p = document.createElement("p");
        p.textContent = content;

        bubble.appendChild(small);
        bubble.appendChild(p);
        wrapper.appendChild(bubble);
        chatHistory.appendChild(wrapper);

        // Scroll dentro del chatWrapper
        if (chatWrapper) {
            requestAnimationFrame(() => {
                chatWrapper.scrollTop = chatWrapper.scrollHeight;
            });
        }
    }

    // ============================================================
    //  ENVÍO AL AGENTE
    // ============================================================
    async function enviarAlAgente(texto) {
        addChatBubble("user", "message", texto);

        try {
            const response = await fetch(URL_CONSULTA, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": getCsrfToken()
                },
                body: JSON.stringify({ texto })
            });

            const data = await response.json();

            if (!response.ok) {
                addChatBubble("assistant", "error", data.error || "Error al consultar al agente.");
                return;
            }

            addChatBubble("assistant", data.tipo || "message", data.respuesta || "");
        } catch (error) {
            addChatBubble("assistant", "error", "No se pudo enviar el texto al agente.");
        }
    }

    // ============================================================
    //  GRABACIÓN DE VOZ
    // ============================================================
    const DURACION_MINIMA_MS = 400;
    const UMBRAL_CANCELAR_PX = 80;
    const TOPE_DESLIZAMIENTO_PX = 120; // distancia máxima que se puede arrastrar hacia la izquierda
    let grabacionEnCurso = false;
    let inicioGrabacion = 0;
    let inicioTouchX = 0;
    let grabacionCancelada = false;

    function obtenerX(event) {
        if (event.touches && event.touches.length > 0) return event.touches[0].clientX;
        if (typeof event.clientX === "number") return event.clientX;
        return 0;
    }

    // Alterna entre el cuadro de texto normal y el aviso de "desliza para
    // cancelar", igual que hace WhatsApp mientras se está grabando audio.
    function mostrarModoGrabacion(activo) {
        if (activo) {
            inputWrapper.classList.add("hidden");
            grabandoHint.classList.remove("hidden");
        } else {
            inputWrapper.classList.remove("hidden");
            grabandoHint.classList.add("hidden");
            grabandoHint.classList.remove("cancelando");
        }
    }

    async function empezarGrabacion(event) {
        event.preventDefault();
        if (grabacionEnCurso) return;

        inicioTouchX = obtenerX(event);
        grabacionCancelada = false;

        try {
            const stream = await navigator.mediaDevices.getUserMedia({
                audio: {
                    noiseSuppression: true,
                    echoCancellation: true,
                    autoGainControl: true
                }
            });

            activeStream = stream;
            audioChunks = [];
            resetVoiceBlock();
            grabacionEnCurso = true;
            inicioGrabacion = Date.now();

            let mimeType = "audio/webm";
            if (window.MediaRecorder && MediaRecorder.isTypeSupported("audio/webm;codecs=opus")) {
                mimeType = "audio/webm;codecs=opus";
            }

            mediaRecorder = new MediaRecorder(stream, { mimeType });

            mediaRecorder.ondataavailable = (e) => {
                if (e.data.size > 0) {
                    audioChunks.push(e.data);
                }
            };

            mediaRecorder.onstop = async () => {
                const fueCancelada = grabacionCancelada;
                grabacionCancelada = false;

                if (fueCancelada) {
                    audioChunks = [];
                    stopTracks();
                    mostrarEstadoGrabacion("Grabación cancelada.", 1500);
                    return;
                }

                const duracion = Date.now() - inicioGrabacion;

                if (duracion < DURACION_MINIMA_MS) {
                    mostrarEstadoGrabacion("");
                    stopTracks();
                    return;
                }

                mostrarEstadoGrabacion("Transcribiendo audio...");

                const blob = new Blob(audioChunks, { type: mimeType });
                const formData = new FormData();
                formData.append("audio", blob, "grabacion.webm");

                try {
                    const response = await fetch(URL_SPEECH_TO_TEXT, {
                        method: "POST",
                        headers: {
                            "X-CSRFToken": getCsrfToken()
                        },
                        body: formData
                    });

                    const data = await response.json();

                    if (!response.ok) {
                        bloqueVoz.classList.add("hidden");
                        addChatBubble("assistant", "error", data.error || "No se pudo transcribir el audio.");
                        mostrarEstadoGrabacion("");
                        return;
                    }

                    textoPendienteConfirmacion = data.texto_transcrito || "";
                    textoTranscrito.textContent = textoPendienteConfirmacion;

                    bloqueVoz.classList.remove("hidden");
                    btnConfirmarTexto.classList.remove("hidden");
                    btnCancelarTexto.classList.remove("hidden");
                    mostrarEstadoGrabacion("Texto transcrito. Confirma si quieres enviarlo al agente.");

                    if (chatWrapper) {
                        requestAnimationFrame(() => {
                            chatWrapper.scrollTop = chatWrapper.scrollHeight;
                        });
                    }
                } catch (error) {
                    bloqueVoz.classList.add("hidden");
                    addChatBubble("assistant", "error", "No se pudo enviar el audio al servidor.");
                    mostrarEstadoGrabacion("");
                } finally {
                    stopTracks();
                }
            };

            mediaRecorder.start();
            btnGrabar.classList.add("recording");
            mostrarModoGrabacion(true);
            mostrarEstadoGrabacion("Grabando... suelta para enviar.");
        } catch (error) {
            grabacionEnCurso = false;
            mostrarEstadoGrabacion("No se pudo acceder al micrófono.");
        }
    }

    function manejarDeslizamientoGrabacion(event) {
        if (!grabacionEnCurso) return;

        const x = obtenerX(event);
        let deltaX = Math.min(0, x - inicioTouchX); // solo interesa el movimiento hacia la izquierda
        deltaX = Math.max(deltaX, -TOPE_DESLIZAMIENTO_PX); // tope: no se desplaza más allá de este límite

        const transformDeslizamiento = deltaX ? `translateX(${deltaX}px)` : "";
        btnGrabar.style.transform = transformDeslizamiento;
        grabandoHint.style.transform = transformDeslizamiento;

        const debeCancelar = deltaX <= -UMBRAL_CANCELAR_PX;
        if (debeCancelar !== grabacionCancelada) {
            grabacionCancelada = debeCancelar;
            btnGrabar.classList.toggle("cancelando", debeCancelar);
            grabandoHint.classList.toggle("cancelando", debeCancelar);
            mostrarEstadoGrabacion(
                debeCancelar ? "Suelta para cancelar" : "Grabando... suelta para enviar."
            );
        }
    }

    function pararGrabacion() {
        if (!grabacionEnCurso) return;
        grabacionEnCurso = false;
        btnGrabar.classList.remove("recording", "cancelando");
        btnGrabar.style.transform = "";
        grabandoHint.style.transform = "";
        mostrarModoGrabacion(false); // vuelve a mostrar el cuadro de texto
        if (mediaRecorder && mediaRecorder.state !== "inactive") {
            mediaRecorder.stop();
            mostrarEstadoGrabacion(grabacionCancelada ? "Grabación cancelada." : "Deteniendo grabación...");
        }
    }

    btnGrabar.addEventListener("mousedown", empezarGrabacion);
    btnGrabar.addEventListener("mouseup", pararGrabacion);
    btnGrabar.addEventListener("mouseleave", pararGrabacion);
    btnGrabar.addEventListener("touchstart", empezarGrabacion, { passive: false });
    btnGrabar.addEventListener("touchmove", manejarDeslizamientoGrabacion, { passive: false });
    btnGrabar.addEventListener("touchend", pararGrabacion);
    btnGrabar.addEventListener("touchcancel", pararGrabacion);

    // Confirmar / cancelar texto transcrito
    btnConfirmarTexto.addEventListener("click", async () => {
        if (!textoPendienteConfirmacion) return;
        const texto = textoPendienteConfirmacion;
        resetVoiceBlock();
        bloqueVoz.classList.add("hidden");
        mostrarEstadoGrabacion("Enviando texto al agente...");
        await enviarAlAgente(texto);
        mostrarEstadoGrabacion("Consulta procesada.", 2500);
    });

    btnCancelarTexto.addEventListener("click", () => {
        resetVoiceBlock();
        bloqueVoz.classList.add("hidden");
        mostrarEstadoGrabacion("Texto descartado.", 2000);
    });

    // ============================================================
    //  ENVÍO POR TECLADO
    // ============================================================
    formTexto.addEventListener("submit", async (event) => {
        event.preventDefault();
        const texto = textoInput.value.trim();
        if (!texto) return;

        if (texto.toLowerCase() === "reset" || texto.toLowerCase() === "reiniciar") {
            textoInput.value = "";
            await hacerReset();
            return;
        }

        btnEnviarTexto.disabled = true;
        textoInput.value = "";
        textoInput.blur();
        await enviarAlAgente(texto);
        btnEnviarTexto.disabled = false;
    });

    // ============================================================
    //  COMANDOS SILENCIOSOS (reset, vaciar chat)
    // ============================================================
    async function enviarComandoSilencioso(comando) {
        const response = await fetch(URL_CONSULTA, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-CSRFToken": getCsrfToken()
            },
            body: JSON.stringify({ texto: comando })
        });
        return response.json();
    }

    async function hacerReset() {
        try {
            const data = await enviarComandoSilencioso("reset");
            chatHistory.innerHTML = "";
            actualizarVisibilidadBotonScroll();
            addChatBubble("assistant", "system", data.respuesta || "Contexto borrado.");
        } catch (error) {
            addChatBubble("assistant", "error", "No se pudo reiniciar el contexto.");
        }
    }

    async function hacerVaciarChat() {
        try {
            await enviarComandoSilencioso("vaciar_chat");
            chatHistory.innerHTML = "";
            actualizarVisibilidadBotonScroll();
        } catch (error) {
            addChatBubble("assistant", "error", "No se pudo vaciar el chat.");
        }
    }

    // ============================================================
    //  BOTÓN SCROLL ABAJO
    // ============================================================
    const UMBRAL_CERCA_DEL_FINAL_PX = 150;

    function estaCercaDelFinal() {
        if (!chatWrapper) return true;
        const distancia = chatWrapper.scrollHeight - chatWrapper.scrollTop - chatWrapper.clientHeight;
        return distancia < UMBRAL_CERCA_DEL_FINAL_PX;
    }

    function actualizarVisibilidadBotonScroll() {
        if (estaCercaDelFinal()) {
            btnScrollAbajo.classList.add("hidden");
        } else {
            btnScrollAbajo.classList.remove("hidden");
        }
    }

    if (chatWrapper) {
        chatWrapper.addEventListener("scroll", actualizarVisibilidadBotonScroll);
        window.addEventListener("resize", actualizarVisibilidadBotonScroll);
        actualizarVisibilidadBotonScroll();
    }

    btnScrollAbajo.addEventListener("click", () => {
        if (chatWrapper) {
            chatWrapper.scrollTo({
                top: chatWrapper.scrollHeight,
                behavior: "smooth"
            });
        }
    });

    // ============================================================
    //  OVERLAY Y PANELES (menú lateral, avatar, modal)
    // ============================================================
    const overlay = document.getElementById("overlay");
    const menuAvatar = document.getElementById("menuAvatar");
    const modalPerfil = document.getElementById("modalPerfil");

    const TODOS_LOS_PANELES = [menuAvatar, modalPerfil];

    function cerrarTodosLosPaneles() {
        TODOS_LOS_PANELES.forEach((panel) => {
            panel.classList.remove("visible");
            panel.classList.add("hidden");
        });
        overlay.classList.remove("visible");
        overlay.classList.add("hidden");
    }

    function abrirPanel(panel) {
        cerrarTodosLosPaneles();
        panel.classList.remove("hidden");
        requestAnimationFrame(() => {
            requestAnimationFrame(() => {
                panel.classList.add("visible");
            });
        });
        overlay.classList.remove("hidden");
        requestAnimationFrame(() => {
            overlay.classList.add("visible");
        });
    }

    overlay.addEventListener("click", cerrarTodosLosPaneles);

    document.getElementById("btnAvatarMenu").addEventListener("click", (event) => {
        event.stopPropagation();
        abrirPanel(menuAvatar);
    });

    document.getElementById("btnResetContextoMenu").addEventListener("click", async () => {
        cerrarTodosLosPaneles();
        await hacerReset();
    });

    document.getElementById("btnVaciarChat").addEventListener("click", async () => {
        cerrarTodosLosPaneles();
        await hacerVaciarChat();
    });

    document.getElementById("btnVerPerfil").addEventListener("click", () => {
        abrirPanel(modalPerfil);
    });

    document.getElementById("btnConsultasEjemplo").addEventListener("click", () => {
        if (URL_EXAMPLES) window.location.href = URL_EXAMPLES;
    });
    document.getElementById("btnCerrarModalPerfil").addEventListener("click", cerrarTodosLosPaneles);

    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
            cerrarTodosLosPaneles();
        }
    });

})();