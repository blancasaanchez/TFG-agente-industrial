(function () {
    "use strict";

    // URLs desde el script tag
    const scriptTag = document.currentScript;
    const URL_INDEX = scriptTag.dataset.urlIndex;

    
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

    document.getElementById("btnVerPerfil").addEventListener("click", () => {
        abrirPanel(modalPerfil);
    });

    document.getElementById("btnInicio").addEventListener("click", () => {
        if (URL_INDEX) window.location.href = URL_INDEX;
    });
    document.getElementById("btnCerrarModalPerfil").addEventListener("click", cerrarTodosLosPaneles);

    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
            cerrarTodosLosPaneles();
        }
    });

    // ============================================================
    //  COPIAR CONSULTAS DE EJEMPLO
    // ============================================================
    document.querySelectorAll(".btn-copiar").forEach((boton) => {
        boton.addEventListener("click", async () => {
            const texto = boton.dataset.texto || "";
            if (!texto) return;

            try {
                await navigator.clipboard.writeText(texto);
            } catch (error) {
                // Fallback por si el navegador no permite el portapapeles
                // (por ejemplo, sin conexión https)
                const areaTemporal = document.createElement("textarea");
                areaTemporal.value = texto;
                areaTemporal.style.position = "fixed";
                areaTemporal.style.opacity = "0";
                document.body.appendChild(areaTemporal);
                areaTemporal.select();
                try { document.execCommand("copy"); } catch (e) { /* nada más que hacer */ }
                document.body.removeChild(areaTemporal);
            }

            const textoOriginal = boton.textContent;
            boton.textContent = "¡Copiado!";
            boton.classList.add("copiado");
            setTimeout(() => {
                boton.textContent = textoOriginal;
                boton.classList.remove("copiado");
            }, 1500);
        });
    });

})();