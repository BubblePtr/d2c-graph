import androidx.compose.ui.window.Window
import androidx.compose.ui.window.application
import androidx.compose.ui.window.exitApplication

fun main() = application {
    Window(onCloseRequest = ::exitApplication, title = "d2c-kmp-template") {
        App()
    }
}
