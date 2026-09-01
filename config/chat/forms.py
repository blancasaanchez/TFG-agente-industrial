from django import forms


class PreguntaForm(forms.Form):
    pregunta = forms.CharField(
        label="Escribe tu pregunta",
        max_length=200,
        widget=forms.TextInput(attrs={
            "placeholder": "Ejemplo: qué máquinas están averiadas",
            "class": "form-control"
        })
    )