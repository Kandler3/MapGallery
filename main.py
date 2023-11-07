import exifread
from PyQt5.QtGui import QPixmap, QPainter, QIcon
from PyQt5.QtWidgets import QMainWindow, QApplication, QFileDialog, QWidget, QTableWidget
from PyQt5.QtWebEngineWidgets import QWebEngineView
from PyQt5 import uic
from PyQt5.QtCore import Qt
import sys
import folium
import io
from PIL import Image as PilImage, ImageOps
import sqlite3
import os


class Images:
    """Класс для доступа к базе изображений"""

    def __init__(self):
        self.con = sqlite3.connect('images_db.sqlite')
        cur = self.con.cursor()
        tables = cur.execute('''SELECT name FROM sqlite_schema
                            WHERE type ='table' AND name NOT LIKE 'sqlite_%';''').fetchone()
        if tables is None or 'images' not in tables:
            print('creating new table')
            cur.execute('''CREATE TABLE images (
                            id         INTEGER PRIMARY KEY AUTOINCREMENT
                               NOT NULL
                               UNIQUE,
                            full_image TEXT,
                            icon       TEXT,
                            latitude   REAL,
                            longitude  REAL
                            )''')
            self.con.commit()

        self.directory = os.path.dirname(os.path.abspath(sys.argv[0]))

    def add_image(self, image_path):
        """Обрабатывает добавление изобрадения в базу и создание иконки для карты"""

        cur = self.con.cursor()
        cur.execute('INSERT INTO images(full_image) VALUES("temp")')
        self.con.commit()
        img_id = cur.lastrowid
        print(img_id)
        ext = image_path[image_path.rfind('.'):]
        new_image_path = os.path.join(self.directory, 'images', str(img_id) + ext)
        icon_path = os.path.join(self.directory, 'icons', str(img_id) + ext)
        with PilImage.open(image_path) as img:
            img = ImageOps.exif_transpose(img)
            icon_img = img.resize((100, 100))
            img.save(new_image_path)
            icon_img.save(icon_path)

        latitude, longitude = self.get_image_location(image_path)

        cur = self.con.cursor()
        cur.execute('''UPDATE images
                        SET full_image = ?, icon = ?, LATITUDE = ?, longitude = ?
                        WHERE id = ?''',
                    (new_image_path, icon_path, latitude, longitude, img_id))

        self.con.commit()
        return cur.lastrowid, new_image_path, icon_path, latitude, longitude

    def delete_image(self, img_id):
        """Обрабатывает удаление изображения"""

        cur = self.con.cursor()
        img_path, icon_path = cur.execute(f'''SELECT full_image, icon FROM images
                                          WHERE id = ?''', (img_id,)).fetchone()
        os.remove(img_path)
        os.remove(icon_path)
        cur.execute(f'''DELETE FROM images
                        WHERE id = ?''', (img_id,))
        self.con.commit()

    def get_images(self):
        """Возвращает список параметров всех изображений"""

        cur = self.con.cursor()
        images = cur.execute('SELECT * FROM images').fetchall()
        return images

    def get_image_info(self, img_id):
        """Возвращает параметры одного изображения"""

        cur = self.con.cursor()
        res = cur.execute('''SELECT * FROM images
                            WHERE id = ?''', (img_id,)).fetchall()[0]
        return res

    def get_image_location(self, image_path):
        """Возвращает координаты локации изображения"""

        def convert_latitude(latitude_ref, latitude_data):
            """Конвертирует широту в десятичные градусы"""

            latitude = [float(i) for i in latitude_data.values]
            res = latitude[0] + latitude[1] / 60 + latitude[2] / 3600
            if latitude_ref.values[0] == 'S':
                res = -res
            return res

        def convert_longitude(longitude_ref, longitude_data):
            """Конвертирует долготу в десятичные градусы"""

            longitude = [float(i) for i in longitude_data.values]
            res = longitude[0] + longitude[1] / 60 + longitude[2] / 3600
            if longitude_ref.values[0] == 'W':
                res = -res
            return res

        with open(image_path, 'rb') as file:
            image_data = exifread.process_file(file)
            try:
                latitude = convert_latitude(image_data['GPS GPSLatitudeRef'], image_data['GPS GPSLatitude'])
                longitude = convert_longitude(image_data['GPS GPSLongitudeRef'], image_data['GPS GPSLongitude'])
            except KeyError:
                print(f"Image '{image_path}' does not have coordinates")
                return None, None
        return latitude, longitude

    def clear(self):
        """Очищает базу данных"""

        cur = self.con.cursor()
        cur.execute('DELETE FROM images')
        self.con.commit()


class ImageWidget(QWidget):
    def __init__(self, image_id, image_path, resolution=None, parent=None):
        super(ImageWidget, self).__init__(parent)
        self.path = image_path
        self.resolution = resolution
        self.id = image_id
        self.update_image()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self.image)

    def update_image(self):
        """При вызове обновляет собственное изображение на актуальное"""

        self.image = QPixmap(self.path)
        if self.resolution is not None:
            self.image = self.image.scaled(*self.resolution, Qt.KeepAspectRatioByExpanding)
        self.update()


class ImageWindow(QMainWindow):
    def __init__(self, image_id, index, main_window):
        super(ImageWindow, self).__init__()
        uic.loadUi('image.ui', self)
        self.resize(800, 1000)
        self.id = image_id
        self.main = main_window
        self.index = index
        print(self.main)
        self.info = self.main.images.get_image_info(self.id)
        self.image_widget = ImageWidget(self.id, self.info[1], (700, 700), parent=self)
        self.mainLayout.addWidget(self.image_widget)

        self.directory = os.path.dirname(os.path.abspath(sys.argv[0]))
        clockwise_icon = QIcon(os.path.join(self.directory, 'buttons', 'clockwise.png'))
        counterclockwise_icon = QIcon(os.path.join(self.directory, 'buttons', 'counterclockwise.png'))
        self.rotateClockwiseButton.setIcon(clockwise_icon)
        self.rotateCounterclockwiseButton.setIcon(counterclockwise_icon)

        self.rotateCounterclockwiseButton.clicked.connect(self.rotate_counterclockwise_button_handler)
        self.rotateClockwiseButton.clicked.connect(self.rotate_clockwise_button_handler)

    def rotate_clockwise_button_handler(self):
        self.rotate_image(-90)

    def rotate_counterclockwise_button_handler(self):
        self.rotate_image(90)

    def rotate_image(self, angle):
        """Вращает против часовой стрелки собственное изображение на заданный угол"""

        with PilImage.open(self.info[1]) as img:
            img = img.rotate(angle, expand=True)
            img.save(self.info[1])
            icon_img = img.resize((100, 100))
            icon_img.save(self.info[2])
        self.image_widget.update_image()

    def closeEvent(self, event):
        self.main.imageTable.update_image(self.index)
        self.main.update_map()


class ImagesTableWidget(QTableWidget):
    def __init__(self, images_per_row, parent=None):
        super(ImagesTableWidget, self).__init__(parent)
        self.parent = parent
        self.images_per_row = images_per_row
        self.images = parent.images

        self.cellDoubleClicked.connect(self.open_image_window)
        self.load_widgets()
        self.update_photos_layout()

    def load_widgets(self):
        """Создает виджеты всех изображений из базы данных"""

        self.widgets = []
        for image_info in self.images.get_images():
            image_id = image_info[0]
            image_path = image_info[1]
            image = ImageWidget(image_id, image_path, (300, 300), self)
            self.widgets.append(image)

    def update_photos_layout(self):
        """Загружает виджеты изображений в таблицу"""

        self.clear_photos_layout()
        rows = len(self.widgets) // self.images_per_row + 1
        self.setRowCount(rows)
        self.setColumnCount(self.images_per_row)
        for col in range(self.images_per_row):
            self.setColumnWidth(col, 300)
        for row in range(rows):
            self.setRowHeight(row, 300)
        for index, image in enumerate(self.widgets):
            row = index // self.images_per_row
            col = index % self.images_per_row
            print(index, row, col)
            self.setCellWidget(row, col, image)

    def update_image(self, index):
        """Обновляет заданное изображение"""

        row = index // self.images_per_row
        col = index % self.images_per_row
        self.removeCellWidget(row, col)
        old_img = self.widgets[index]
        image_path = self.images.get_image_info(old_img.id)[1]
        print(f'updating image {old_img.id} with {image_path=}')
        image = ImageWidget(old_img.id, image_path, (300, 300), self)
        self.setCellWidget(row, col, image)
        self.widgets[index] = image

    def clear_photos_layout(self):
        """Очищает таблицу от всех виджетов"""

        for row in range(self.rowCount()):
            for col in range(self.columnCount()):
                self.removeCellWidget(row, col)
        self.setRowCount(0)

    def open_image_window(self, row, col):
        """Создает и открывает окно с заданным изображением"""

        index = row * self.images_per_row + col
        if index >= len(self.widgets):
            return

        image = self.widgets[index]
        print(self.parent)
        image_window = ImageWindow(image.id, index, self.parent)
        image_window.show()
        self.parent.image_windows.append(image_window)

    def set_images_per_row(self, images_per_row):
        """Устанавливает новое количество изображений в одном ряду таблицы"""

        if self.images_per_row != images_per_row:
            self.images_per_row = images_per_row
            self.load_widgets()
            self.update_photos_layout()

    def delete_selected(self):
        """Удаляет все выбранные изображения"""

        images = []
        for index in self.selectedIndexes():
            row, col = index.row(), index.column()
            index = row * self.images_per_row + col
            if index < len(self.widgets):
                images.append(self.widgets[index])
                self.widgets[index] = None

        return images


class MyWidget(QMainWindow):
    def __init__(self):
        super(MyWidget, self).__init__()
        uic.loadUi('main.ui', self)
        self.setMinimumSize(1000, 800)
        self.setWindowTitle('Map Gallery')
        self.images = Images()
        self.imageTable = ImagesTableWidget(3, self)
        self.photosTab.layout().addWidget(self.imageTable)
        self.image_windows = []
        self.map_init()

        self.tabWidget.setTabText(0, 'Карта')
        self.tabWidget.setTabText(1, 'Галерея')

        self.addPhotosButton.clicked.connect(self.add_photos_button_handler)
        self.deletePhotosButton.clicked.connect(self.delete_photos_button_handler)

    def map_init(self):
        """Инициализирует объект карты"""

        self.map = folium.Map(zoom_start=10,
                              location=(55.752900, 37.622107))
        for image_info in self.images.get_images():
            icon, *location = image_info[2:]
            if location != (None, None):
                self.add_image_marker(icon, location)
        self.update_map()

    def resizeEvent(self, event):
        """Обновляет размер виджета с картой"""

        super().resizeEvent(event)
        self.webview.resize(self.width(), self.height())
        self.imageTable.set_images_per_row(self.width() // 300)

    def add_photos_button_handler(self):
        """Обрабатывает добавление фотографий"""

        dialog = QFileDialog()
        dialog.setFileMode(QFileDialog.ExistingFiles)
        if dialog.exec_():
            file_names = dialog.selectedFiles()
        if 'file_names' not in locals():
            return
        for image_path in file_names:
            icon, *location = self.images.add_image(image_path)[2:]
            if location != (None, None):
                self.add_image_marker(icon, location)
        self.imageTable.load_widgets()
        self.imageTable.update_photos_layout()
        self.update_map()

    def delete_photos_button_handler(self):
        """Обрабатывает удаление фотографий"""

        images = self.imageTable.delete_selected()

        if not images:
            self.statusBar().showMessage('Ни одна фотография не выбрана')
        else:
            self.statusBar().clearMessage()
            for image in images:
                self.images.delete_image(image.id)
                print(f'image {image.id} deleted')

            self.imageTable.load_widgets()
            self.imageTable.update_photos_layout()
            self.update_map()

    def add_image_marker(self, image_name, coords):
        """Добавляет маркер с фотографией на карту"""

        icon = folium.CustomIcon(icon_image=image_name, icon_size=(100, 100))
        folium.Marker(location=coords, icon=icon).add_to(self.map)

    def update_map(self):
        """Обновляет карту"""

        data = io.BytesIO()
        self.map.save(data, close_file=False)
        if self.mapWidget.children():
            self.mapWidget.children()[-1].hide()
        self.webview = QWebEngineView(self.mapWidget)
        self.webview.resize(self.width(), self.height())
        self.webview.setHtml(data.getvalue().decode())
        print('map updated')
        print(self.mapWidget.children())


if __name__ == '__main__':
    app = QApplication(sys.argv)
    ex = MyWidget()
    ex.show()
    sys.exit(app.exec())
