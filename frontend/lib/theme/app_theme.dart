import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

class AppColors {
  static const primary = Color(0xFF1A6E35);
  static const primaryDark = Color(0xFF0D5C2C);
  static const primaryLight = Color(0xFFE8F5EE);
  static const orange = Color(0xFFE55A00);
  static const orangeLight = Color(0xFFFFF0E6);
  static const mtn = Color(0xFFC7960A);
  static const mtnLight = Color(0xFFFFFBEB);
  static const moov = Color(0xFF0048C8);
  static const moovLight = Color(0xFFE6EEFF);
  static const blue = Color(0xFF1A6AF5);
  static const blueLight = Color(0xFFE8F4FC);
  static const purple = Color(0xFF7C3AED);
  static const purpleLight = Color(0xFFF5F0FF);
  static const red = Color(0xFFDC2626);
  static const redLight = Color(0xFFFEF2F2);
  static const amber = Color(0xFFD97706);
  static const amberLight = Color(0xFFFFF8EB);
  static const background = Color(0xFFFFFFFF);
  static const card = Colors.white;
  static const textPrimary = Color(0xFF050A3A);
  static const textSecondary = Color(0xFF404A73);
  static const textHint = Color(0xFF697093);
  static const divider = Color(0xFFE8EAF1);
  static const success = Color(0xFF078C3A);

  static Color operatorColor(String op) {
    switch (op) {
      case 'Orange': return orange;
      case 'MTN': return mtn;
      case 'Moov': return moov;
      default: return primary;
    }
  }

  static Color operatorBg(String op) {
    switch (op) {
      case 'Orange': return orangeLight;
      case 'MTN': return mtnLight;
      case 'Moov': return moovLight;
      default: return primaryLight;
    }
  }
}

class AppTheme {
  static ThemeData get theme => ThemeData(
    useMaterial3: true,
    colorScheme: ColorScheme.fromSeed(seedColor: AppColors.primary),
    textTheme: GoogleFonts.nunitoTextTheme(),
    scaffoldBackgroundColor: AppColors.background,
    pageTransitionsTheme: const PageTransitionsTheme(
      builders: {
        TargetPlatform.android: ZoomPageTransitionsBuilder(),
        TargetPlatform.iOS: ZoomPageTransitionsBuilder(),
      },
    ),
    appBarTheme: AppBarTheme(
      backgroundColor: AppColors.primary,
      foregroundColor: Colors.white,
      elevation: 0,
      titleTextStyle: GoogleFonts.nunito(
        fontSize: 20, fontWeight: FontWeight.w900, color: Colors.white,
      ),
    ),
  );
}
