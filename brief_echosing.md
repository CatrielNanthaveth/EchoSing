# Brief del Proyecto: App de Karaoke Impulsada por IA (Nombre en clave: EchoSing)

## 1. Resumen Ejecutivo (Project Brief)
EchoSing es una aplicación interactiva de karaoke que utiliza modelos avanzados de Inteligencia Artificial para ofrecer una experiencia inmersiva y gamificada. A diferencia de los sistemas de karaoke tradicionales que dependen de pistas instrumentales prefabricadas y archivos de sincronización manual, esta plataforma procesa cualquier canción original para aislar las voces, extraer las letras con precisión de milisegundos y mapear la curva de afinación del artista original. Posteriormente, evalúa en tiempo real la interpretación del usuario comparando su voz con la referencia matemática de la pista original, otorgando un puntaje dinámico estrofa por estrofa.

## 2. Alcance del Proyecto
**Fase 1 (MVP):**
*   Ingesta asíncrona de canciones procesadas en el backend (creación del catálogo).
*   Reproductor móvil/web con visualización de letras sincronizadas y pista instrumental.
*   Captura de audio del usuario segmentada por versos.
*   Cálculo de puntaje de afinación local o vía WebSockets por cada verso completado.
*   Pantalla de resultados finales (precisión general, mejor racha).

**Fuera del alcance (Fase 1):**
*   Procesamiento de canciones subidas por el usuario "en vivo" (requiere mucha capacidad de GPU).
*   Multijugador en tiempo real o batallas sincrónicas.
*   Aplicación de efectos de audio en tiempo real sobre la voz del usuario (reverb/autotune de baja latencia).

## 3. Características Principales
*   **Separador de Pistas Mágico:** Convierte cualquier tema comercial en una pista de karaoke de alta fidelidad.
*   **Smart-Sync Lyrics:** Las letras aparecen en pantalla en el milisegundo exacto, generadas automáticamente mediante reconocimiento de voz.
*   **Pitch-Matching por Estrofa:** Al finalizar cada línea de la canción, el usuario recibe retroalimentación visual inmediata sobre su afinación.
*   **Puntuación Dinámica:** Algoritmo que compensa el tempo natural del usuario (Dynamic Time Warping) para puntuar la afinación sin penalizar ligeros retrasos rítmicos.
*   **Modo de Práctica:** Visualización de la "curva de afinación" ideal frente a la curva del usuario en una gráfica de líneas, ideal para mejorar el canto.

## 4. Stack Tecnológico Propuesto

### Backend (Procesamiento Asíncrono e Infraestructura)
*   **Lenguaje / Framework:** Python con FastAPI (para la API REST y WebSockets).
*   **Procesamiento Asíncrono:** Celery + Redis o RabbitMQ (vital para manejar las colas de separación de audio sin bloquear el servidor).
*   **Modelos de IA (Pipeline de Ingesta):**
    *   *Separación de Fuentes:* **Demucs v4** (Meta) o Spleeter para extraer la pista instrumental.
    *   *Transcripción y Timestamps:* **Whisper** (OpenAI) con alineación a nivel de palabra/verso.
    *   *Extracción de Afinación (F0):* **CREPE** (preferible por su alta precisión en voces).
*   **Base de Datos:** PostgreSQL para usuarios, metadatos de canciones y puntajes históricos. MongoDB para almacenar los JSONs estructurados de las letras y curvas F0.
*   **Almacenamiento:** AWS S3 o Google Cloud Storage para archivos `.m4a` o `.mp3` generados.

### Frontend (Aplicación de Usuario)
*   **Framework:** React Native (con Expo Audio) o Flutter. Esto permite compilar para iOS y Android con una sola base de código.
*   **Procesamiento Edge (Cliente):**
    *   Uso de C++ / WebAssembly o librerías nativas (como `aubio` o un modelo ONNX ligero) para ejecutar el algoritmo **YIN** en el dispositivo móvil y extraer la afinación del usuario sin enviar el audio de vuelta al servidor.
*   **Animaciones:** Reanimated (React Native) o Rive para lograr barras de progreso y puntajes fluidos a 60fps.

## 5. Recomendaciones y Desafíos Técnicos

1.  **Arquitectura "Edge-first" para la puntuación:** Enviar archivos de audio desde el teléfono al servidor por cada estrofa generará cuellos de botella e incrementará los costos de servidor. La extracción de la curva de tono del usuario DEBE ocurrir en el dispositivo móvil. Al servidor solo se le envía un array numérico para guardar el puntaje o, en su defecto, el cliente calcula el algoritmo DTW localmente.
2.  **Calibración de Latencia Bluetooth:** Los auriculares inalámbricos introducen un retraso (lag) de entre 40ms y 200ms. Es indispensable implementar un flujo de "calibración" en la app donde el usuario toca la pantalla al escuchar un pitido, para que el sistema ajuste los *timestamps* antes de calcular el puntaje de afinación.
3.  **Procesamiento por Lotes (Catálogo cerrado):** En lugar de permitir que cada usuario procese canciones nuevas bajo demanda (lo cual agotaría tu cuota de GPU rápidamente), inicia con un catálogo pre-procesado. Si los usuarios piden canciones, entra a una cola de votación y el sistema las procesa en horas valle.
