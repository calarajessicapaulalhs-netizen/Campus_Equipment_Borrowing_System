from datetime import timedelta

from django import forms
from django.contrib.auth import authenticate
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.db.models import Count, Q
from django.utils import timezone

from .models import (
    BorrowRequest,
    CatalogItem,
    Category,
    EquipmentUnit,
    MaintenanceRecord,
    SystemSetting,
    User,
)


class RegistrationForm(UserCreationForm):
    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150)
    email = forms.EmailField()

    class Meta(UserCreationForm.Meta):
        model = User
        fields = (
            "username",
            "first_name",
            "last_name",
            "email",
            "phone",
        )

    def _post_clean(self):
        super()._post_clean()
        password2_errors = self._errors.get("password2")
        if not password2_errors:
            return

        errors = password2_errors.as_data()
        confirm_errors = [
            error for error in errors
            if error.code in {"required", "password_mismatch"}
        ]
        password_requirements = [
            error for error in errors
            if error.code not in {"required", "password_mismatch"}
        ]
        for error in password_requirements:
            self.add_error("password1", error)

        if confirm_errors:
            self._errors["password2"] = self.error_class(confirm_errors)
        else:
            del self._errors["password2"]

    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = User.Role.BASIC_USER
        user.is_active = True

        if commit:
            user.save()

        return user


class SignInForm(AuthenticationForm):
    def clean(self):
        username = self.cleaned_data.get("username")
        password = self.cleaned_data.get("password")

        if username is not None and password:
            user_candidate = User.objects.filter(username=username).first()
            if not user_candidate and "@" in username:
                user_candidate = User.objects.filter(email__iexact=username).first()

            if user_candidate and not user_candidate.is_active:
                raise forms.ValidationError(
                    "Your account has been deactivated by an administrator. Please contact the campus equipment administration to reactivate your access.",
                    code="inactive",
                )

            self.user_cache = authenticate(
                self.request, username=username, password=password
            )
            if self.user_cache is None:
                raise self.get_invalid_login_error()
            else:
                self.confirm_login_allowed(self.user_cache)

        return self.cleaned_data


class ProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["first_name", "last_name", "email", "phone"]


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ["name", "description"]


class CatalogItemForm(forms.ModelForm):
    class Meta:
        model = CatalogItem
        fields = ["category", "name", "description"]


class EquipmentUnitForm(forms.ModelForm):
    quantity = forms.IntegerField(
        min_value=1,
        max_value=100,
        initial=1,
        help_text=(
            "Register 1–100 physical units. For more than one, the system "
            "adds -001, -002, and so on to the asset code."
        ),
    )

    class Meta:
        model = EquipmentUnit
        fields = ["asset_code", "item", "condition", "acquired_on"]

    def add_error(self, field, error):
        super().add_error(field, error)
        if field in self.fields:
            classes = self.fields[field].widget.attrs.get("class", "" ).split()
            if "auth-input-invalid" not in classes:
                classes.append("auth-input-invalid")
                self.fields[field].widget.attrs["class"] = " ".join(classes)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["asset_code"].label = "Asset code or prefix"
        self.fields["asset_code"].help_text = (
            "One unit uses this exact code. Multiple units receive a numbered suffix."
        )


class EquipmentUnitEditForm(forms.ModelForm):
    class Meta:
        model = EquipmentUnit
        fields = ["condition", "acquired_on"]


class RequestForm(forms.ModelForm):
    class Meta:
        model = BorrowRequest
        fields = ["purpose", "due_date"]
        widgets = {
            "due_date": forms.DateInput(attrs={"type": "date"}),
        }

    def clean_due_date(self):
        due_date = self.cleaned_data["due_date"]
        today = timezone.localdate()
        max_days = SystemSetting.current().max_loan_days

        if due_date <= today or due_date > today + timedelta(days=max_days):
            raise forms.ValidationError(
                f"Choose a date within {max_days} calendar days."
            )

        return due_date


class RequestLineForm(forms.Form):
    item = forms.ModelChoiceField(
        queryset=CatalogItem.objects.none(),
        required=False,
    )
    quantity = forms.IntegerField(
        min_value=1,
        required=False,
    )

    def add_error(self, field, error):
        super().add_error(field, error)
        if field in self.fields:
            classes = self.fields[field].widget.attrs.get("class", "" ).split()
            if "auth-input-invalid" not in classes:
                classes.append("auth-input-invalid")
                self.fields[field].widget.attrs["class"] = " ".join(classes)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        qs = (
            CatalogItem.objects.filter(
                is_active=True,
                category__is_active=True,
            )
            .annotate(
                available_count=Count(
                    "units",
                    filter=Q(units__status=EquipmentUnit.Status.AVAILABLE),
                )
            )
            .order_by("name")
        )
        self.fields["item"].queryset = qs
        self.fields["item"].label_from_instance = lambda obj: (
            f"{obj.name} ({getattr(obj, 'available_count', 0)} available)"
            if getattr(obj, "available_count", 0) > 0
            else f"{obj.name} (Unavailable - 0 left)"
        )

    def clean(self):
        cleaned_data = super().clean()
        item = cleaned_data.get("item")
        quantity = cleaned_data.get("quantity")
        if item:
            available_count = item.units.filter(status=EquipmentUnit.Status.AVAILABLE).count()
            if available_count <= 0:
                self.add_error("item", f"{item.name} is currently unavailable and cannot be borrowed.")
            elif quantity and quantity > available_count:
                self.add_error("quantity", f"Only {available_count} unit(s) of {item.name} are available.")
        return cleaned_data


class DecisionForm(forms.Form):
    decision = forms.ChoiceField(
        choices=[
            ("approve", "Approve"),
            ("reject", "Reject"),
        ],
    )
    reason = forms.CharField(
        widget=forms.Textarea,
        required=False,
    )

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get("decision") and not cleaned_data.get("reason", "").strip():
            self.add_error("reason", "Record a reason for this decision.")
        return cleaned_data


class ReturnForm(forms.Form):
    condition = forms.ChoiceField(
        choices=EquipmentUnit.Condition.choices,
    )
    return_date = forms.DateField(
        label="Date returned",
        initial=timezone.localdate,
        widget=forms.DateInput(attrs={"type": "date"}),
    )

    def clean_return_date(self):
        return_date = self.cleaned_data["return_date"]
        if return_date > timezone.localdate():
            raise forms.ValidationError("Return date cannot be in the future.")
        return return_date


class MaintenanceForm(forms.ModelForm):
    class Meta:
        model = MaintenanceRecord
        fields = ["unit", "problem"]
        widgets = {
            "problem": forms.Textarea,
        }


class CloseMaintenanceForm(forms.Form):
    OUTCOME_CHOICES = [
        ('AVAILABLE', 'Release as Available (Repaired)'),
        ('RETIRED', 'Retire Unit (Unserviceable / Beyond repair)'),
    ]
    action = forms.CharField(
        widget=forms.Textarea(attrs={
            'rows': 4,
            'placeholder': 'Describe repair work performed, parts replaced, or reason for retirement...',
            'style': 'width: 100%; box-sizing: border-box;',
        }),
        label='Action Taken / Resolution Notes',
        help_text='Detailed notes on the maintenance action performed.',
    )
    outcome = forms.ChoiceField(
        choices=OUTCOME_CHOICES,
        initial='AVAILABLE',
        required=False,
        widget=forms.RadioSelect,
        label='Unit Outcome',
        help_text='Repaired units return to Available stock. Retired units stay unavailable.',
    )


class DueDateForm(forms.Form):
    due_date = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    reason = forms.CharField(widget=forms.Textarea)

    def clean_due_date(self):
        due_date = self.cleaned_data["due_date"]
        today = timezone.localdate()
        max_days = SystemSetting.current().max_loan_days
        allowed_window = max(max_days, 30)

        if due_date <= today:
            raise forms.ValidationError("Choose a future date.")
        if due_date > today + timedelta(days=allowed_window):
            raise forms.ValidationError(
                f"Due date cannot be scheduled beyond {allowed_window} days from today."
            )

        return due_date


class SettingForm(forms.ModelForm):
    class Meta:
        model = SystemSetting
        fields = ["max_loan_days", "max_quantity"]

    def clean_max_loan_days(self):
        max_days = self.cleaned_data["max_loan_days"]
        if not 1 <= max_days <= 60:
            raise forms.ValidationError(
                "Set a duration between 1 and 60 days."
            )
        return max_days

    def clean_max_quantity(self):
        max_quantity = self.cleaned_data["max_quantity"]
        if not 1 <= max_quantity <= 20:
            raise forms.ValidationError(
                "Set a quantity between 1 and 20."
            )
        return max_quantity

