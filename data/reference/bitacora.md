# Bitácora de campaña

Registro de toda intervención física o evento externo que afecte la continuidad del
registro. Sin esta anotación, una discontinuidad en los datos resulta indistinguible
de un fallo del instrumento (protocolo §11).

Las horas de las interrupciones provienen de `detectar_huecos` y corresponden al
último intervalo registrado antes del corte y al primero tras la recuperación, en
hora local.

| Fecha | Hora local | Nodo | Evento | Causa | Registró |
|---|---|---|---|---|---|
| 2026-09-15 | 16:45 | ues-b1c9fe | Inicio de la campaña | — | NVC |
| 2026-09-22 | 15:15 – 16:05 | ues-b1c9fe | Interrupción, 8 intervalos | No registrada | NVC |
| 2026-10-04 | 01:35 – 15:20 | ues-b1c9fe | Interrupción, 164 intervalos | Corte del suministro eléctrico comercial | NVC |
| 2026-10-04 | 15:20 – 05:55 (+1 d) | ues-b1c9fe | Interrupción, 174 intervalos | Corte del suministro eléctrico comercial | NVC |
| 2026-10-06 | 08:30 – 09:50 | ues-b1c9fe | Interrupción, 15 intervalos | Corte del suministro eléctrico comercial | NVC |
| 2026-10-06 | 10:05 – 10:25 | ues-b1c9fe | Interrupciones breves, 2 intervalos | Corte del suministro eléctrico comercial | NVC |
| 2026-10-06 | 19:00 – 19:15 | ues-b1c9fe | Interrupción, 2 intervalos | No registrada | NVC |

## Observaciones

Los ocho arranques registrados durante la campaña declaran como causa
`External System`: ninguno corresponde a un reinicio espontáneo del firmware.

Las interrupciones del 4 y 5 de octubre suman 28 horas continuas sin registro.
El nodo carece de respaldo energético, de modo que un corte del suministro detiene
la medición, no solo la transmisión. Este evento constituye el sustento empírico del
requisito de batería para campañas de co-ubicación de 28 días (protocolo §5.3).
