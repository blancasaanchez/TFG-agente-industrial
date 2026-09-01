from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group

class Command(BaseCommand):
    help = "Crea los grupos de roles del sistema"

    def handle(self, *args, **kwargs):
        for nombre in ["administrador", "supervisor", "operario"]:
            group, created = Group.objects.get_or_create(name=nombre)
            if created:
                self.stdout.write(f"Grupo '{nombre}' creado.")
            else:
                self.stdout.write(f"Grupo '{nombre}' ya existía.")