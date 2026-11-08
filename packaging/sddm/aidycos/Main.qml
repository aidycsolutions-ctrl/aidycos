import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

Item {
    id: root
    width: Screen.width
    height: Screen.height

    readonly property color bgColor: "#000000"
    readonly property color surfaceColor: "#141414"
    readonly property color textColor: "#F4F4F4"
    readonly property color mutedColor: "#A8A8A8"
    readonly property color borderColor: "#2A2A2A"
    readonly property color accentColor: "#1EC8E8"

    property int sessionIndex: sessionModel.lastIndex
    property string errorText: ""

    function doLogin() {
        errorText = ""
        sddm.login(usernameField.text, passwordField.text, sessionIndex)
    }

    Rectangle {
        anchors.fill: parent
        color: root.bgColor
    }

    Image {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.top: parent.top
        anchors.topMargin: Math.max(28, parent.height * 0.05)
        width: Math.min(280, parent.width * 0.26, parent.height * 0.30)
        height: width
        source: "aidycos.png"
        fillMode: Image.PreserveAspectFit
        asynchronous: true
        cache: true
    }

    Item {
        id: form
        width: Math.min(380, parent.width * 0.86)
        height: formColumn.implicitHeight + 48
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: Math.max(48, parent.height * 0.08)

        Rectangle {
            anchors.fill: parent
            radius: 16
            color: root.surfaceColor
            border.color: root.borderColor
            border.width: 1
        }

        ColumnLayout {
            id: formColumn
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: 24
            spacing: 14

            TextField {
                id: usernameField
                Layout.fillWidth: true
                text: userModel.lastUser
                placeholderText: "Usuario"
                color: root.textColor
                placeholderTextColor: root.mutedColor
                selectByMouse: true
                background: Rectangle {
                    radius: 8
                    color: root.bgColor
                    border.color: usernameField.activeFocus ? root.accentColor : root.borderColor
                    border.width: 1
                }
                onAccepted: passwordField.forceActiveFocus()
            }

            TextField {
                id: passwordField
                Layout.fillWidth: true
                placeholderText: "Contraseña"
                echoMode: TextInput.Password
                color: root.textColor
                placeholderTextColor: root.mutedColor
                selectByMouse: true
                background: Rectangle {
                    radius: 8
                    color: root.bgColor
                    border.color: passwordField.activeFocus ? root.accentColor : root.borderColor
                    border.width: 1
                }
                onAccepted: root.doLogin()
            }

            ComboBox {
                id: sessionCombo
                Layout.fillWidth: true
                visible: sessionModel.count > 1
                model: sessionModel
                textRole: "name"
                currentIndex: sessionModel.lastIndex
                onCurrentIndexChanged: root.sessionIndex = currentIndex
                contentItem: Text {
                    leftPadding: 12
                    text: sessionCombo.displayText
                    color: root.textColor
                    verticalAlignment: Text.AlignVCenter
                    elide: Text.ElideRight
                }
                background: Rectangle {
                    radius: 8
                    color: root.bgColor
                    border.color: root.borderColor
                    border.width: 1
                }
            }

            Text {
                Layout.fillWidth: true
                visible: root.errorText.length > 0
                text: root.errorText
                color: "#FF6B8A"
                wrapMode: Text.WordWrap
                horizontalAlignment: Text.AlignHCenter
                font.pixelSize: 13
            }

            Button {
                id: loginButton
                Layout.fillWidth: true
                text: "Entrar"
                onClicked: root.doLogin()
                contentItem: Text {
                    text: loginButton.text
                    color: "#041014"
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    font.pixelSize: 15
                    font.weight: Font.Medium
                }
                background: Rectangle {
                    radius: 8
                    color: root.accentColor
                    opacity: loginButton.down ? 0.75 : 1.0
                }
            }
        }
    }

    Connections {
        target: sddm
        function onLoginFailed() {
            root.errorText = "Acceso denegado"
            passwordField.text = ""
            passwordField.forceActiveFocus()
        }
        function onLoginSucceeded() {
            root.errorText = ""
        }
    }

    Component.onCompleted: {
        if (usernameField.text.length > 0)
            passwordField.forceActiveFocus()
        else
            usernameField.forceActiveFocus()
    }
}
