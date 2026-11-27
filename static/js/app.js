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

  const errorSummary = document.querySelector(".error-summary");
  if (errorSummary) {
    errorSummary.focus();
  }

  document.querySelectorAll("[data-custom-select]").forEach((customSelect) => {
    const nativeSelect = customSelect.querySelector("select");
    const trigger = customSelect.querySelector(".custom-select-trigger");
    const list = customSelect.querySelector('[role="listbox"]');
    if (!nativeSelect || !trigger || !list) return;

    const label = document.querySelector(`label[for="${nativeSelect.id}"]`);
    trigger.setAttribute("aria-label", label ? label.textContent.trim() : nativeSelect.name);
    nativeSelect.setAttribute("aria-hidden", "true");
    nativeSelect.tabIndex = -1;
    nativeSelect.classList.add("custom-select-native");
    customSelect.classList.add("is-enhanced");

    const triggerLabel = document.createElement("span");
    trigger.appendChild(triggerLabel);

    const options = Array.from(nativeSelect.options).map((nativeOption, index) => {
      const option = document.createElement("li");
      option.className = "custom-select-option";
      option.id = `${nativeSelect.id}-option-${index}`;
      option.setAttribute("role", "option");
      option.setAttribute("aria-selected", "false");
      option.dataset.value = nativeOption.value;

      const text = document.createElement("span");
      text.textContent = nativeOption.textContent;
      text.title = nativeOption.textContent;
      option.appendChild(text);
      list.appendChild(option);
      return option;
    });

    let activeIndex = Math.max(nativeSelect.selectedIndex, 0);

    const sync = () => {
      const selected = nativeSelect.options[nativeSelect.selectedIndex];
      triggerLabel.textContent = selected ? selected.textContent : "";
      trigger.title = selected ? selected.textContent : "";
      options.forEach((option, index) => {
        const selectedOption = index === nativeSelect.selectedIndex;
        option.classList.toggle("is-selected", selectedOption);
        option.setAttribute("aria-selected", selectedOption ? "true" : "false");
        option.classList.remove("is-active");
      });
      activeIndex = nativeSelect.selectedIndex >= 0 ? nativeSelect.selectedIndex : 0;
      trigger.removeAttribute("aria-activedescendant");
    };

    const close = (returnFocus = false) => {
      list.hidden = true;
      trigger.setAttribute("aria-expanded", "false");
      trigger.removeAttribute("aria-activedescendant");
      options.forEach((option) => option.classList.remove("is-active"));
      if (returnFocus) trigger.focus();
    };

    const setActive = (index) => {
      if (!options.length) return;
      activeIndex = (index + options.length) % options.length;
      options.forEach((option) => option.classList.remove("is-active"));
      const option = options[activeIndex];
      option.classList.add("is-active");
      trigger.setAttribute("aria-activedescendant", option.id);
      const optionTop = option.offsetTop;
      const optionBottom = optionTop + option.offsetHeight;
      if (optionTop < list.scrollTop) list.scrollTop = optionTop;
      if (optionBottom > list.scrollTop + list.clientHeight) {
        list.scrollTop = optionBottom - list.clientHeight;
      }
    };

    const open = (activateSelected = true) => {
      document.dispatchEvent(new CustomEvent("custom-select-open", { detail: customSelect }));
      list.hidden = false;
      trigger.setAttribute("aria-expanded", "true");
      list.scrollTop = 0;
      if (activateSelected) {
        setActive(nativeSelect.selectedIndex >= 0 ? nativeSelect.selectedIndex : 0);
        const active = options[activeIndex];
        if (active) {
          if (active.offsetTop < list.scrollTop) list.scrollTop = active.offsetTop;
          if (active.offsetTop + active.offsetHeight > list.scrollTop + list.clientHeight) {
            list.scrollTop = active.offsetTop + active.offsetHeight - list.clientHeight;
          }
        }
      }
    };

    const selectIndex = (index) => {
      if (index < 0 || index >= nativeSelect.options.length) return;
      nativeSelect.selectedIndex = index;
      sync();
      nativeSelect.dispatchEvent(new Event("change", { bubbles: true }));
      close(true);
    };

    trigger.addEventListener("click", () => {
      if (list.hidden) open();
      else close();
    });

    trigger.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        if (list.hidden) open();
        else selectIndex(activeIndex);
      } else if (event.key === "ArrowDown") {
        event.preventDefault();
        if (list.hidden) open();
        else setActive(activeIndex + 1);
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        if (list.hidden) {
          open(false);
          setActive(nativeSelect.selectedIndex >= 0 ? nativeSelect.selectedIndex : options.length - 1);
        } else {
          setActive(activeIndex - 1);
        }
      } else if (event.key === "Home" && !list.hidden) {
        event.preventDefault();
        setActive(0);
      } else if (event.key === "End" && !list.hidden) {
        event.preventDefault();
        setActive(options.length - 1);
      } else if (event.key === "Escape" && !list.hidden) {
        event.preventDefault();
        close();
      } else if (event.key === "Tab") {
        close();
      } else if (event.key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey) {
        const query = event.key.toLowerCase();
        const found = options.findIndex((option) => option.textContent.trim().toLowerCase().startsWith(query));
        if (found >= 0) {
          event.preventDefault();
          open();
          setActive(found);
        }
      }
    });

    list.addEventListener("keydown", (event) => {
      if (event.key === "ArrowDown") {
        event.preventDefault();
        setActive(activeIndex + 1);
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        setActive(activeIndex - 1);
      } else if (event.key === "Home") {
        event.preventDefault();
        setActive(0);
      } else if (event.key === "End") {
        event.preventDefault();
        setActive(options.length - 1);
      } else if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        selectIndex(activeIndex);
      } else if (event.key === "Escape") {
        event.preventDefault();
        close(true);
      } else if (event.key === "Tab") {
        close();
      }
    });

    options.forEach((option, index) => {
      option.addEventListener("pointerdown", (event) => {
        event.preventDefault();
        selectIndex(index);
      });
    });

    nativeSelect.addEventListener("change", sync);
    if (nativeSelect.form) {
      nativeSelect.form.addEventListener("reset", () => window.setTimeout(sync, 0));
    }
    document.addEventListener("custom-select-open", (event) => {
      if (event.detail !== customSelect) close();
    });
    document.addEventListener("search-combobox-open", () => close());
    document.addEventListener("pointerdown", (event) => {
      if (!customSelect.contains(event.target)) close();
    });
    sync();
  });

  document.querySelectorAll("[data-search-combobox]").forEach((combobox) => {
    const input = combobox.querySelector('input[role="combobox"]');
    const list = combobox.querySelector('[role="listbox"]');
    if (!input || !list) return;

    const allOptions = Array.from(list.querySelectorAll('[role="option"]'));
    if (!allOptions.length) return;

    let activeIndex = -1;
    let visibleOptions = [];

    const setActive = (option) => {
      allOptions.forEach((item) => {
        item.setAttribute("aria-selected", "false");
        item.classList.remove("is-active");
      });
      input.removeAttribute("aria-activedescendant");
      activeIndex = option ? visibleOptions.indexOf(option) : -1;
      if (option) {
        option.setAttribute("aria-selected", "true");
        option.classList.add("is-active");
        input.setAttribute("aria-activedescendant", option.id);
        const optionTop = option.offsetTop;
        const optionBottom = optionTop + option.offsetHeight;
        if (optionTop < list.scrollTop) list.scrollTop = optionTop;
        if (optionBottom > list.scrollTop + list.clientHeight) {
          list.scrollTop = optionBottom - list.clientHeight;
        }
      }
    };

    const close = () => {
      list.hidden = true;
      input.setAttribute("aria-expanded", "false");
      setActive(null);
      const emptyMessage = combobox.querySelector(".search-no-suggestions");
      if (emptyMessage) emptyMessage.remove();
    };

    const open = () => {
      document.dispatchEvent(new CustomEvent("search-combobox-open", { detail: combobox }));
      const query = input.value.trim().toLowerCase();
      visibleOptions = allOptions
        .filter((option) => (option.dataset.search || "").toLowerCase().includes(query))
        .sort((a, b) => {
          if (!query) return 0;
          const aText = (a.dataset.search || "").toLowerCase();
          const bText = (b.dataset.search || "").toLowerCase();
          const aStarts = aText.startsWith(query) ? 0 : 1;
          const bStarts = bText.startsWith(query) ? 0 : 1;
          return aStarts - bStarts;
        });

      allOptions.forEach((option) => {
        option.hidden = !visibleOptions.includes(option);
        option.classList.remove("is-active");
        option.setAttribute("aria-selected", "false");
      });
      input.removeAttribute("aria-activedescendant");
      activeIndex = -1;
      list.scrollTop = 0;

      const existingMessage = combobox.querySelector(".search-no-suggestions");
      if (existingMessage) existingMessage.remove();

      if (visibleOptions.length) {
        list.hidden = false;
        input.setAttribute("aria-expanded", "true");
      } else {
        list.hidden = false;
        input.setAttribute("aria-expanded", "true");
        const message = document.createElement("li");
        message.className = "search-no-suggestions";
        message.setAttribute("role", "presentation");
        message.textContent = "No suggestions - press Enter to search";
        list.appendChild(message);
      }
    };

    input.addEventListener("focus", open);
    input.addEventListener("click", open);
    input.addEventListener("input", open);
    document.addEventListener("custom-select-open", () => close());

    input.addEventListener("keydown", (event) => {
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        if (list.hidden) open();
        if (!visibleOptions.length) return;
        if (event.key === "ArrowDown") {
          activeIndex = activeIndex < visibleOptions.length - 1 ? activeIndex + 1 : 0;
        } else {
          activeIndex = activeIndex > 0 ? activeIndex - 1 : visibleOptions.length - 1;
        }
        setActive(visibleOptions[activeIndex]);
      } else if (event.key === "Home" && !list.hidden && visibleOptions.length) {
        event.preventDefault();
        setActive(visibleOptions[0]);
      } else if (event.key === "End" && !list.hidden && visibleOptions.length) {
        event.preventDefault();
        setActive(visibleOptions[visibleOptions.length - 1]);
      } else if (event.key === "Enter") {
        if (!list.hidden && activeIndex >= 0 && visibleOptions[activeIndex]) {
          event.preventDefault();
          input.value = visibleOptions[activeIndex].dataset.value;
          input.closest("form").requestSubmit();
        }
      } else if (event.key === "Escape") {
        event.preventDefault();
        close();
      } else if (event.key === "Tab") {
        close();
      }
    });

    allOptions.forEach((option) => {
      option.addEventListener("pointerdown", (event) => {
        event.preventDefault();
        input.value = option.dataset.value;
        input.closest("form").requestSubmit();
      });
    });

    document.addEventListener("pointerdown", (event) => {
      if (!combobox.contains(event.target)) close();
    });
  });
})();
