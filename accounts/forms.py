from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm, UserCreationForm

from .models import Department, UserProfile
from .roles import ROLES


def _apply_input_class(form):
    for field in form.fields.values():
        if isinstance(field.widget, forms.CheckboxInput):
            continue
        classes = field.widget.attrs.get("class", "").split()
        if "input" not in classes:
            classes.append("input")
        field.widget.attrs["class"] = " ".join(classes)
    return form


def _apply_native_field_guidance(form):
    for name, field in form.fields.items():
        auto_id = field.widget.attrs.get("id") or form[name].auto_id
        help_id = f"{auto_id}-help"
        error_id = f"{auto_id}-error"
        described_by = []
        if field.help_text:
            described_by.append(help_id)

        if name in form.errors:
            described_by.append(error_id)
            field.widget.attrs["aria-invalid"] = "true"
        else:
            field.widget.attrs.pop("aria-invalid", None)

        if described_by:
            field.widget.attrs["aria-describedby"] = " ".join(described_by)
        else:
            field.widget.attrs.pop("aria-describedby", None)
    return form


class _NativeFieldGuidanceMixin:
    def add_error(self, field, error):
        super().add_error(field, error)
        _apply_native_field_guidance(self)


class StyledAuthenticationForm(AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_input_class(self)


class StyledPasswordChangeForm(PasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_input_class(self)


ROLE_CHOICES = [("", "No SIA role")] + [
    (role["slug"], role["label"]) for role in ROLES
]


class SystemAdminAccountCreateForm(_NativeFieldGuidanceMixin, UserCreationForm):
    first_name = forms.CharField(max_length=150, required=False)
    last_name = forms.CharField(max_length=150, required=False)
    email = forms.EmailField(required=False)
    is_active = forms.BooleanField(required=False, initial=True)
    role = forms.ChoiceField(choices=ROLE_CHOICES, required=False)
    department = forms.ModelChoiceField(queryset=Department.objects.all(), required=False)
    employee_id = forms.CharField(max_length=30, required=False)

    class Meta(UserCreationForm.Meta):
        model = get_user_model()
        fields = ("username", "first_name", "last_name", "email")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_input_class(self)
        self.fields["email"].help_text = "Use an address that the account holder can receive."
        self.fields["employee_id"].help_text = "Use the employee identifier assigned by the organization."
        self.fields["department"].empty_label = "Select department"
        self.fields["department"].help_text = "Optional. Choose the department this account belongs to."
        self.fields["role"].help_text = "Assign at most one recognized SIA role."
        self.fields["is_active"].label = "Active account"
        self.fields["is_active"].help_text = "Allows this user to sign in immediately after the account is created."
        self.fields["username"].widget.attrs.update({
            "autocomplete": "username",
            "maxlength": str(self.fields["username"].max_length),
        })
        self.fields["first_name"].widget.attrs.update({
            "autocomplete": "given-name",
            "maxlength": str(self.fields["first_name"].max_length),
        })
        self.fields["last_name"].widget.attrs.update({
            "autocomplete": "family-name",
            "maxlength": str(self.fields["last_name"].max_length),
        })
        self.fields["email"].widget.attrs.update({
            "autocomplete": "email",
            "inputmode": "email",
            "maxlength": str(self.fields["email"].max_length),
        })
        self.fields["password1"].widget.attrs.update({"autocomplete": "new-password"})
        self.fields["password2"].widget.attrs.update({"autocomplete": "new-password"})
        self.fields["employee_id"].widget.attrs.update({
            "autocomplete": "off",
            "maxlength": str(self.fields["employee_id"].max_length),
        })
        _apply_native_field_guidance(self)

    def clean_role(self):
        value = self.cleaned_data["role"]
        allowed = {slug for slug, _label in ROLE_CHOICES if slug}
        if value and value not in allowed:
            raise forms.ValidationError("Unknown or unsupported SIA role.")
        return value


class SystemAdminAccountEditForm(_NativeFieldGuidanceMixin, forms.ModelForm):
    role = forms.ChoiceField(choices=ROLE_CHOICES, required=False)
    department = forms.ModelChoiceField(queryset=Department.objects.all(), required=False)
    employee_id = forms.CharField(max_length=30, required=False)

    class Meta:
        model = get_user_model()
        fields = ("first_name", "last_name", "email", "is_active")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        profile = getattr(self.instance, "profile", None)
        self.fields["role"].initial = next(
            (
                group.name
                for group in self.instance.groups.all()
                if group.name in {item["slug"] for item in ROLES}
            ),
            "",
        )
        self.fields["department"].initial = profile.department if profile else None
        self.fields["employee_id"].initial = profile.employee_id if profile else ""
        _apply_input_class(self)
        self.fields["email"].help_text = "Use an address that the account holder can receive."
        self.fields["employee_id"].help_text = "Use the employee identifier assigned by the organization."
        self.fields["department"].empty_label = "Select department"
        self.fields["department"].help_text = "Optional. Choose the department this account belongs to."
        self.fields["role"].help_text = "Assign at most one recognized SIA role."
        self.fields["is_active"].label = "Active account"
        self.fields["is_active"].help_text = "Allows this user to sign in while the account remains active."
        self.fields["first_name"].widget.attrs.update({
            "autocomplete": "given-name",
            "maxlength": str(self.fields["first_name"].max_length),
        })
        self.fields["last_name"].widget.attrs.update({
            "autocomplete": "family-name",
            "maxlength": str(self.fields["last_name"].max_length),
        })
        self.fields["email"].widget.attrs.update({
            "autocomplete": "email",
            "inputmode": "email",
            "maxlength": str(self.fields["email"].max_length),
        })
        self.fields["employee_id"].widget.attrs.update({
            "autocomplete": "off",
            "maxlength": str(self.fields["employee_id"].max_length),
        })
        _apply_native_field_guidance(self)

    def clean_role(self):
        value = self.cleaned_data["role"]
        allowed = {role["slug"] for role in ROLES}
        if value and value not in allowed:
            raise forms.ValidationError("Unknown or unsupported SIA role.")
        return value
