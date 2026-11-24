(() => {
  const themeButton = document.querySelector(".theme-btn");
  const root = document.documentElement;

  if (themeButton) {
    const updateThemeLabel = () => {
      const action = root.dataset.theme === "dark"
        ? "Switch to light theme"
        : "Switch to dark theme";
      themeButton.setAttribute("aria-label", action);
      themeButton.title = action;
    };

    try {
      const savedTheme = window.localStorage.getItem("sia-theme");
      if (savedTheme === "light" || savedTheme === "dark") {
        root.dataset.theme = savedTheme;
      }
    } catch (error) {
      console.error("Unable to read the saved theme preference.", error);
    }
    updateThemeLabel();

    themeButton.addEventListener("click", () => {
      const nextTheme = root.dataset.theme === "dark" ? "light" : "dark";
      root.dataset.theme = nextTheme;
      updateThemeLabel();
      try {
        window.localStorage.setItem("sia-theme", nextTheme);
      } catch (error) {
        console.error("Unable to save the theme preference.", error);
      }
    });
  }

  document.querySelectorAll("form").forEach((form) => {
    const onceButton = form.querySelector(
      'button[type="submit"][data-once], input[type="submit"][data-once]',
    );
    if (!onceButton) return;

    form.addEventListener("submit", (event) => {
      if (form.dataset.onceSubmitted === "true") {
        event.preventDefault();
        return;
      }
      form.dataset.onceSubmitted = "true";
      onceButton.disabled = true;
    });
  });
})();
