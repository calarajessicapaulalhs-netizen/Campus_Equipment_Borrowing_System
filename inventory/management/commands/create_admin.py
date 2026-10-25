from getpass import getpass

from django.core.management.base import BaseCommand

from inventory.models import User


class Command(BaseCommand):
    help = "Create an ADMIN account interactively."

    def handle(self, *args, **options):
        username = input("Username: ").strip()
        password = getpass("Password (min 10 characters): ")
        if len(password) < 10:
            raise SystemExit("Password must have at least 10 characters.")

        user = User.objects.create_user(
            username=username,
            password=password,
            role=User.Role.ADMIN,
            is_staff=False,
            is_superuser=False,
        )
        self.stdout.write(
            self.style.SUCCESS(f"Created admin account {user.username}.")
        )

