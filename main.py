import exifread
from PyQt5.QtGui import QPixmap, QPainter
from PyQt5.QtWidgets import QMainWindow, QApplication, QVBoxLayout, QFileDialog, QWidget, QLabel, QSizePolicy, \
    QTableWidget
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
    """Класс для доступа к базе фотографий"""

    def __init__(self):
        self.con = sqlite3.connect('images_db.sqlite')
        self.directory = os.path.dirname(os.path.abspath(sys.argv[0]))

    def add_image(self, image_path):
        try:
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
            if cur.lastrowid != img_id:
                raise ValueError('НЕ РАБОТАЕТ АЛЛО АЛЛР')
            return cur.lastrowid, new_image_path, icon_path, latitude, longitude
        except Exception as err:
            print(err.__repr__())

    def delete_image(self, img_id):
        try:
            cur = self.con.cursor()
            img_path, icon_path = cur.execute(f'''SELECT full_image, icon FROM images
                                              WHERE id = ?''', (img_id,)).fetchone()
            os.remove(img_path)
            os.remove(icon_path)
            cur.execute(f'''DELETE FROM images
                            WHERE id = ?''', (img_id,))
            self.con.commit()
        except Exception as err:
            print(err.__repr__())

    def get_images(self):
        cur = self.con.cursor()
        images = cur.execute('SELECT * FROM images').fetchall()
        return images

    def get_image_info(self, img_id):
        cur = self.con.cursor()
        res = cur.execute('''SELECT * FROM images
                            WHERE id = ?''', (img_id,)).fetchall()[0]
        return res

    def get_image_location(self, image_path):
        """Возвращает координаты локации фотографии"""

        def convert_latitude(latitude_ref, latitude_data):
            latitude = [float(i) for i in latitude_data.values]
            res = latitude[0] + latitude[1] / 60 + latitude[2] / 3600
            if latitude_ref.values[0] == 'S':
                res = -res
            return res

        def convert_longitude(longitude_ref, longitude_data):
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
                return None
        return latitude, longitude

    def clear(self):
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
        self.image = QPixmap(self.path)
        if self.resolution is not None:
            self.image = self.image.scaled(*self.resolution, Qt.KeepAspectRatioByExpanding)
        self.update()


class ImageWindow(QMainWindow):
    def __init__(self, image_id, row, col, main_window):
        super(ImageWindow, self).__init__()
        uic.loadUi('image.ui', self)
        self.resize(800, 1000)
        self.id = image_id
        self.main = main_window
        self.row = row
        self.col = col
        self.info = main_window.images.get_image_info(self.id)
        self.image_widget = ImageWidget(self.id, self.info[1], (700, 700), parent=self)
        self.mainLayout.addWidget(self.image_widget)

        self.rotateCounterclockwiseButton.clicked.connect(self.rotate_counterclockwise_button_handler)
        self.rotateClockwiseButton.clicked.connect(self.rotate_clockwise_button_handler)

    def rotate_clockwise_button_handler(self):
        self.rotate_image(-90)

    def rotate_counterclockwise_button_handler(self):
        self.rotate_image(90)

    def rotate_image(self, angle):
        with PilImage.open(self.info[1]) as img:
            img = img.rotate(angle, expand=True)
            img.save(self.info[1])
            icon_img = img.resize((100, 100))
            icon_img.save(self.info[2])
        self.image_widget.update_image()

    def closeEvent(self, event):
        self.main.update_photo(self.row, self.col)
        self.main.update_map()
      

class MyWidget(QMainWindow):
    def __init__(self):
        super(MyWidget, self).__init__()
        uic.loadUi('main.ui', self)
        self.setMinimumSize(1000, 800)
        self.setWindowTitle('Map Gallery')
        self.images_per_row = 3
        self.images = Images()
        self.table_widgets = []# Нужен для доступа к виджету фотографии по колонке и столбцу в таблице
        self.image_windows = []
        self.map_init()
        self.update_photos_layout()

        self.tabWidget.setTabText(0, 'Карта')
        self.tabWidget.setTabText(1, 'Галерея')


        self.addPhotosButton.clicked.connect(self.add_photos_button_handler)
        self.deletePhotosButton.clicked.connect(self.delete_photos_button_handler)
        self.photosTable.cellDoubleClicked.connect(self.open_image_window)

    def map_init(self):
        """Инициализирует объект карты"""

        self.map = folium.Map(zoom_start=10,
                              location=(55.752900, 37.622107))
        for image_info in self.images.get_images():
            icon, *location = image_info[2:]
            print(icon, location)
            self.add_image_marker(icon, location)
        self.update_map()

    def resizeEvent(self, event):
        """Обновляет размер виджета с картой"""

        super().resizeEvent(event)
        self.webview.resize(self.width(), self.height())
        if self.images_per_row != self.width() // 300:
            try:
                self.images_per_row = self.width() // 300
                self.update_photos_layout()
            except Exception as err:
                print(err.__repr__())

    def add_photos_button_handler(self):
        """Обрабатывает добавление фотографий"""

        dialog = QFileDialog()
        dialog.setFileMode(QFileDialog.ExistingFiles)
        if dialog.exec_():
            file_names = dialog.selectedFiles()
        for image_path in file_names:
            try:
                icon, *location = self.images.add_image(image_path)[2:]
                self.add_image_marker(icon, location)
                print(f"image '{image_path}' with location {location.__repr__()} added")
            except Exception as err:
                print(err.__repr__())
        self.update_photos_layout()
        self.update_map()

    def delete_photos_button_handler(self):
        """Обрабатывает удаление фотографий"""
        images = []
        for index in self.photosTable.selectedIndexes():
            row, col = index.row(), index.column()
            if self.table_widgets[row][col] is not None:
                images.append(self.table_widgets[row][col])
                self.table_widgets[row][col] = None

        if not images:
            self.statusBar().showMessage('Ни одна фотография не выбрана')
        else:
            self.statusBar().clearMessage()
            for image in images:
                self.images.delete_image(image.id)
                print(f'image {image.id} deleted')

            self.update_photos_layout()
            self.update_map()

    def open_image_window(self, row, col):
        if self.table_widgets[row][col] is None:
            return

        try:
            image = self.table_widgets[row][col]
            image_window = ImageWindow(image.id, row, col, self)
            image_window.show()
            self.image_windows.append(image_window)
        except Exception as err:
            print(err.__repr__())

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

    def update_photos_layout(self):
        """Обновляет галлерею во втрой вкладке"""

        self.clear_photos_layout()
        row, col = -1, 0
        self.photosTable.setColumnCount(self.images_per_row)
        for i in range(self.images_per_row):
            self.photosTable.setColumnWidth(i, 300)
        self.photosTable.setRowHeight(0, 300)
        for image_info in self.images.get_images():
            if col == 0:
                self.photosTable.setRowCount(self.photosTable.rowCount() + 1)
                self.table_widgets.append([None] * self.images_per_row)
                row += 1
                self.photosTable.setRowHeight(row, 300)
            image_id = image_info[0]
            image_path = image_info[1]
            image = ImageWidget(image_id, image_path, (300, 300), self.photosTable)
            self.photosTable.setCellWidget(row, col, image)
            print(self.table_widgets, row, col)
            self.table_widgets[row][col] = image
            col = (col + 1) % self.images_per_row

    def update_photo(self, row, col):
        self.photosTable.removeCellWidget(row, col)
        old_img = self.table_widgets[row][col]
        image_path = self.images.get_image_info(old_img.id)[1]
        print(f'updating image {old_img.id} with {image_path=}')
        image = ImageWidget(old_img.id, image_path, (300, 300), self.photosTable)
        self.photosTable.setCellWidget(row, col, image)
        self.table_widgets[row][col] = image

    def clear_photos_layout(self):
        self.table_widgets = []
        for row in range(self.photosTable.rowCount()):
            for col in range(self.photosTable.columnCount()):
                self.photosTable.removeCellWidget(row, col)
        self.photosTable.setRowCount(0)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_F:
            print('showing map in browser')
            self.map.show_in_browser()

        if event.key() == Qt.Key_Delete:
            self.images.clear()


if __name__ == '__main__':
    app = QApplication(sys.argv)
    ex = MyWidget()
    ex.show()
    sys.exit(app.exec())
