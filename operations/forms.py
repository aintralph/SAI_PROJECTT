from django import forms


class DemonstrationForm(forms.Form):
    demonstration_value = forms.CharField(
        label="Demonstration field",
        help_text="Not connected to a database.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "input"
