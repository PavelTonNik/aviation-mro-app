# Инструкция по добавлению анимации двигателя

## Что сделано:

1. **Создана папка `frontend/assets/`** - для хранения медиа-файлов
2. **Добавлены CSS стили** - для отображения анимации на карточках самолетов
3. **Интегрирована анимация** - в карточки флота на дашборде

## Как добавить свою анимацию:

### Шаг 1: Подготовьте файл анимации

Поддерживаемые форматы:
- **GIF** (рекомендуется) - `engine-animation.gif`
- **WebM** - `engine-animation.webm`
- **MP4** - `engine-animation.mp4`
- **Анимированный SVG** - `engine-animation.svg`

### Шаг 2: Разместите файл в папке assets

Скопируйте ваш файл в:
```
frontend/assets/engine-animation.gif
```

### Шаг 3: (Опционально) Измените формат в коде

Если используете не GIF, откройте `frontend/index.html` и найдите строку:
```html
<img src="assets/engine-animation.gif" alt="Engine" class="engine-animation">
```

Замените расширение файла на ваше (например, `.mp4`, `.webm`).

Для видео используйте тег `<video>`:
```html
<video autoplay loop muted playsinline class="engine-animation">
    <source src="assets/engine-animation.mp4" type="video/mp4">
    <source src="assets/engine-animation.webm" type="video/webm">
</video>
```

## Настройка внешнего вида

В файле `index.html` найдите секцию `/* --- ENGINE ANIMATION STYLES --- */` и измените:

```css
.engine-animation-container {
    width: 120px;      /* Ширина анимации */
    height: 80px;      /* Высота анимации */
    opacity: 0.15;     /* Прозрачность (0.0 - 1.0) */
    bottom: 10px;      /* Отступ снизу */
    right: 10px;       /* Отступ справа */
}

.aircraft-card:hover .engine-animation-container {
    opacity: 0.3;      /* Прозрачность при наведении */
}
```

## Где искать бесплатные анимации двигателей:

1. **Lottie Files** - https://lottiefiles.com/ (анимированные JSON)
2. **Freepik** - https://www.freepik.com/ (GIF, MP4)
3. **Giphy** - https://giphy.com/ (GIF)
4. **Pixabay** - https://pixabay.com/videos/ (MP4)
5. **Pexels** - https://www.pexels.com/videos/ (MP4)

## Результат

Анимация будет отображаться:
- В правом нижнем углу каждой карточки самолета
- С низкой прозрачностью по умолчанию
- Станет ярче при наведении курсора
- Будет полупрозрачной белого цвета (благодаря CSS-фильтру)

## Примечания

- Рекомендуемый размер файла: до 2 МБ
- Рекомендуемое разрешение: 400x300px или меньше
- Для оптимальной производительности используйте оптимизированные GIF или WebM
