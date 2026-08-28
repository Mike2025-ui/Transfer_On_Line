from django import forms

from apps.core.models import USSD_TEMPLATE_KNOWN_VARS, USSD_TEMPLATE_VAR_RE, Operator, Service, UssdCode


class OperatorForm(forms.ModelForm):
    class Meta:
        model = Operator
        fields = ['name', 'code', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'code': forms.TextInput(attrs={'class': 'form-control'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class ServiceForm(forms.ModelForm):
    class Meta:
        model = Service
        fields = ['name', 'code', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'code': forms.TextInput(attrs={'class': 'form-control'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class UssdCodeForm(forms.ModelForm):
    class Meta:
        model = UssdCode
        fields = ['service', 'amount', 'label', 'template', 'is_active', 'is_default']
        widgets = {
            'service': forms.Select(attrs={'class': 'form-select'}),
            'amount': forms.NumberInput(attrs={
                'class': 'form-control', 'step': '1',
                'placeholder': 'Laisser vide = générique (tous montants)',
            }),
            'label': forms.TextInput(attrs={'class': 'form-control'}),
            'template': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '*456*{montant}#'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_default': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def clean_template(self):
        """Same allow-list UssdCode.render() enforces at generation time -
        catching an unknown variable name here means the admin sees the
        mistake immediately instead of it only surfacing the next time a
        real transaction tries to use this template."""
        template = self.cleaned_data['template']
        used = set(USSD_TEMPLATE_VAR_RE.findall(template))
        unknown = used - USSD_TEMPLATE_KNOWN_VARS
        if unknown:
            raise forms.ValidationError(
                f'Variable(s) inconnue(s) : {", ".join(sorted(unknown))}. '
                f'Variables autorisées : {", ".join(sorted(USSD_TEMPLATE_KNOWN_VARS))}.'
            )
        return template
