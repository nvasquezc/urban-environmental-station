#pragma once
// PLANTILLA. Copiar a secrets.h y completar.
// secrets.h esta en .gitignore y NUNCA debe versionarse.
//
//   Copy-Item include\secrets.example.h include\secrets.h

#define WIFI_SSID        "CAMBIAR"
#define WIFI_PASS        "CAMBIAR"

#define FIREBASE_DB_URL  "https://PROYECTO-default-rtdb.firebaseio.com"

// Consola Firebase > Configuracion del proyecto > Cuentas de servicio
//   > Secretos de la base de datos. Son 40 caracteres.
// Un valor de 28 caracteres es un UID de usuario, NO sirve aqui.
#define FIREBASE_SECRET  "CAMBIAR"
