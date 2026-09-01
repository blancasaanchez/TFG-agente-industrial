(function () {
    "use strict";

    const passwordInput = document.getElementById("passwordInput");
    const togglePassword = document.getElementById("togglePassword");
    const loginForm = document.getElementById("loginForm");
    const loginSubmit = document.getElementById("loginSubmit");

    if (togglePassword && passwordInput) {
        const iconEye = togglePassword.querySelector(".icon-eye");
        const iconEyeOff = togglePassword.querySelector(".icon-eye-off");

        togglePassword.addEventListener("click", function () {
            const isPassword = passwordInput.type === "password";
            passwordInput.type = isPassword ? "text" : "password";
            togglePassword.setAttribute("aria-pressed", String(isPassword));
            togglePassword.setAttribute(
                "aria-label",
                isPassword ? "Ocultar contraseña" : "Mostrar contraseña"
            );
            if (iconEye && iconEyeOff) {
                iconEye.classList.toggle("hidden", isPassword);
                iconEyeOff.classList.toggle("hidden", !isPassword);
            }
        });
    }

    if (loginForm && loginSubmit) {
        loginForm.addEventListener("submit", function () {
            loginSubmit.disabled = true;
            loginSubmit.classList.add("is-loading");
            loginSubmit.textContent = "Entrando...";
        });
    }
})();