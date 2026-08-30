// Lumo Greeter - SDDM QML theme for Lumo OS
// Dark glass card over the aurora wallpaper, centered clock, real
// authentication through the SDDM greeter API.
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

import Sddm   // versionless: the qt6 greeter registers its own version

Rectangle {
    id: root

    property string userName: userModel.lastUser
    property int sessionIndex: {
        for (var i = 0; i < sessionModel.count; ++i) {
            if (sessionModel.get(i).key === Sddm.lastSession)
                return i
        }
        return 0
    }
    property string passwordError: ""

    color: "#0b0a14"
    anchors.fill: parent

    SessionModel { id: sessionModel }
    UserModel { id: userModel }

    // wallpaper
    Image {
        anchors.fill: parent
        source: theme.background
        fillMode: Image.PreserveAspectCrop
    }

    Rectangle {
        anchors.fill: parent
        color: "#06071280"
    }

    // ---------- clock (top center) ----------
    Column {
        id: clockBlock
        anchors.top: parent.top
        anchors.topMargin: 64
        anchors.horizontalCenter: parent.horizontalCenter
        spacing: 4

        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: Qt.formatTime(new Date(), "hh:mm AP")
            color: "#f2f1f0"
            font.family: "Inter"
            font.pixelSize: 58
            font.weight: Font.Light
        }
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: Qt.formatDate(new Date(), "dddd, MMMM d yyyy")
            color: "#c9c7e8"
            font.family: "Inter"
            font.pixelSize: 16
        }
    }

    // ---------- login card ----------
    Rectangle {
        id: card
        width: 380
        height: column.implicitHeight + 56
        anchors.centerIn: parent
        color: "#151722e0"
        radius: 22
        border.color: "#ffffff17"
        border.width: 1

        ColumnLayout {
            id: column
            anchors.fill: parent
            anchors.margins: 28
            spacing: 14

            Item {
                Layout.alignment: Qt.AlignHCenter
                width: 84; height: 84

                Rectangle {
                    anchors.fill: parent
                    radius: 26
                    color: "#3584e4"
                }
                Text {
                    anchors.centerIn: parent
                    text: root.userName.length > 0 ? root.userName.substring(0, 1).toUpperCase() : "L"
                    color: "white"
                    font.family: "Inter"
                    font.pixelSize: 38
                    font.weight: Font.Bold
                }
            }

            Label {
                Layout.alignment: Qt.AlignHCenter
                text: {
                    for (var i = 0; i < userModel.count; ++i) {
                        if (userModel.get(i).name === root.userName)
                            return userModel.get(i).realName !== "" ? userModel.get(i).realName : root.userName
                    }
                    return root.userName
                }
                color: "#f2f1f0"
                font.family: "Inter"
                font.pixelSize: 18
                font.weight: Font.DemiBold
            }

            ComboBox {
                id: userCombo
                Layout.fillWidth: true
                model: userModel
                textRole: "name"
                currentIndex: userModel.lastIndex >= 0 ? userModel.lastIndex : 0
                onActivated: {
                    root.userName = userModel.get(currentIndex).name
                    password.text = ""
                    Sddm.authenticate(root.userName)
                }
                background: Rectangle {
                    color: "#ffffff12"
                    radius: 12
                    border.color: "#ffffff20"
                }
                contentItem: Text {
                    text: userCombo.displayText
                    color: "#f2f1f0"
                    font.family: "Inter"
                    font.pixelSize: 14
                    verticalAlignment: Text.AlignVCenter
                    leftPadding: 12
                }
            }

            TextField {
                id: password
                Layout.fillWidth: true
                echoMode: TextInput.Password
                placeholderText: "Password"
                color: "#f2f1f0"
                placeholderTextColor: "#f2f1f070"
                font.family: "Inter"
                font.pixelSize: 15
                enabled: !loginButton.busy
                onAccepted: loginButton.doLogin()
                background: Rectangle {
                    color: "#ffffff12"
                    radius: 12
                    border.color: password.focus ? "#3584e4" : "#ffffff20"
                    border.width: password.focus ? 2 : 1
                }
                leftPadding: 14
                topPadding: 12
                bottomPadding: 12
            }

            Label {
                visible: root.passwordError !== ""
                text: root.passwordError
                color: "#ff8787"
                font.family: "Inter"
                font.pixelSize: 13
                Layout.alignment: Qt.AlignHCenter
            }

            Button {
                id: loginButton
                property bool busy: false
                Layout.fillWidth: true
                text: busy ? "Signing in…" : "Sign in"
                enabled: !busy
                onClicked: doLogin()
                contentItem: Text {
                    text: loginButton.text
                    color: "white"
                    font.family: "Inter"
                    font.pixelSize: 15
                    font.weight: Font.DemiBold
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
                background: Rectangle {
                    color: loginButton.enabled ? "#3584e4" : "#3584e480"
                    radius: 12
                }
                function doLogin() {
                    if (password.text.length === 0)
                        return
                    busy = true
                    Sddm.login(root.userName, password.text, root.sessionIndex)
                }
            }

            // session selector
            RowLayout {
                Layout.fillWidth: true
                spacing: 8

                Text {
                    text: "Session:"
                    color: "#c9c7e8"
                    font.family: "Inter"
                    font.pixelSize: 13
                }
                ComboBox {
                    id: sessionCombo
                    Layout.fillWidth: true
                    model: sessionModel
                    textRole: "name"
                    currentIndex: root.sessionIndex
                    onActivated: root.sessionIndex = currentIndex
                    background: Rectangle {
                        color: "#ffffff10"
                        radius: 10
                        border.color: "#ffffff1c"
                    }
                    contentItem: Text {
                        text: sessionCombo.displayText
                        color: "#f2f1f0"
                        font.family: "Inter"
                        font.pixelSize: 12
                        verticalAlignment: Text.AlignVCenter
                        leftPadding: 10
                        elide: Text.ElideRight
                    }
                }
            }
        }
    }

    // ---------- bottom bar: layout + power ----------
    Row {
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 28
        anchors.horizontalCenter: parent.horizontalCenter
        spacing: 18

        Button {
            visible: Sddm.canSuspend
            width: 44; height: 44
            background: Rectangle { color: "#151722c8"; radius: 14; border.color: "#ffffff1c" }
            contentItem: Text { text: "☾"; color: "#f2f1f0"; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter; font.pixelSize: 18 }
            onClicked: Sddm.suspend()
            ToolTip.visible: hovered
            ToolTip.text: "Suspend"
        }
        Button {
            visible: Sddm.canReboot
            width: 44; height: 44
            background: Rectangle { color: "#151722c8"; radius: 14; border.color: "#ffffff1c" }
            contentItem: Text { text: "⟳"; color: "#f2f1f0"; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter; font.pixelSize: 18 }
            onClicked: Sddm.reboot()
            ToolTip.visible: hovered
            ToolTip.text: "Restart"
        }
        Button {
            visible: Sddm.canPowerOff
            width: 44; height: 44
            background: Rectangle { color: "#151722c8"; radius: 14; border.color: "#ffffff1c" }
            contentItem: Text { text: "⏻"; color: "#f2f1f0"; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter; font.pixelSize: 18 }
            onClicked: Sddm.powerOff()
            ToolTip.visible: hovered
            ToolTip.text: "Shut down"
        }
    }

    // hostname bottom-left
    Text {
        anchors.left: parent.left
        anchors.bottom: parent.bottom
        anchors.margins: 24
        text: Sddm.hostName
        color: "#8f8bb8"
        font.family: "Inter"
        font.pixelSize: 13
    }

    Connections {
        target: Sddm
        function onLoginFailed() {
            root.passwordError = "Wrong password - try again"
            password.text = ""
            loginButton.busy = false
            password.forceActiveFocus()
            Sddm.authenticate(root.userName)
        }
        function onLoginSucceeded() {
            root.passwordError = ""
        }
    }

    Component.onCompleted: Sddm.authenticate(root.userName)
}
