from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm


def _apply_input_class(form):
    for field in form.fields.values():
        classes = field.widget.attrs.get("class", "").split()
        if "input" not in classes:
            classes.append("input")
        field.widget.attrs["class"] = " ".join(classes)
    return form


class StyledAuthenticationForm(AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_input_class(self)


class StyledPasswordChangeForm(PasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_input_class(self)
