// ignore_for_file: avoid_print
import 'dart:io';

void main() {
  final requiredAssets = [
    'assets/images/orange.jpg',
    'assets/images/mtn.jpg',
    'assets/images/moov.jpg',
  ];

  print('🔍 Vérification des images de paiement...');
  bool allGood = true;

  for (var asset in requiredAssets) {
    final file = File(asset);
    if (file.existsSync()) {
      print('✅ Disponible : $asset (${(file.lengthSync() / 1024).toStringAsFixed(2)} KB)');
    } else {
      print('❌ INTROUVABLE : $asset');
      allGood = false;
    }
  }

  if (allGood) {
    print('\n🎉 Tout est parfait ! Vos images sont prêtes pour l\'IA.');
  } else {
    print('\n⚠️ Attention : Corrigez les fichiers manquants avant de continuer.');
  }
}
