// Lumo installer slideshow
import QtQuick
import QtQuick.Controls

Rectangle {
    id: root
    color: "#0b0a14"
    anchors.fill: parent

    Image {
        id: bg
        anchors.fill: parent
        source: "welcome.png"
        fillMode: Image.PreserveAspectCrop
        opacity: 0.35
    }

    Column {
        anchors.centerIn: parent
        spacing: 22
        width: 560

        Image {
            source: "logo.png"
            anchors.horizontalCenter: parent.horizontalCenter
            width: 96; height: 96
            fillMode: Image.PreserveAspectFit
        }

        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: "Welcome to Lumo OS"
            color: "#f2f1f0"
            font.family: "Inter"
            font.pixelSize: 30
            font.weight: Font.Bold
        }

        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
            text: "Featherlight. Fearless. Beautiful.\n" +
                  "An ultra-light Debian 13 desktop built for games, browsers and real work."
            color: "#c9c7e8"
            font.family: "Inter"
            font.pixelSize: 15
        }
    }

    SequentialAnimation on opacity {
        loops: Animation.Infinite
        NumberAnimation { target: root; property: "opacity"; from: 0.92; to: 1.0; duration: 2600 }
        NumberAnimation { target: root; property: "opacity"; from: 1.0; to: 0.92; duration: 2600 }
    }
}
