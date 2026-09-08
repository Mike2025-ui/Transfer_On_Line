import 'package:flutter/material.dart';
import '../services/backend_api_service.dart';
import 'home_screen.dart';

// L’application ne demande plus d’OTP ni de session JWT. Elle ouvre
// directement l’écran d’accueil pour garder le parcours opérateur → service
// → numéro → montant → paiement, sans collecte d’identité supplémentaire.
class SplashScreen extends StatelessWidget {
  const SplashScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return HomeScreen(
      backendApiService: BackendApiService(),
    );
  }
}
