import os

filepath = r'c:\Users\TOSHIBA\Desktop\Transfer_On_Line\backend\apps\core\migrations\0014_create_services.py'

if os.path.exists(filepath):
    os.remove(filepath)
    print(f"✅ Fichier supprimé: {filepath}")
else:
    print(f"❌ Fichier non trouvé: {filepath}")
