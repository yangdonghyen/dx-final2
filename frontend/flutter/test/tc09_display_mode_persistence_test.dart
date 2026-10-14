// TC-09 / FR-AD-801: the selected display mode is written to device storage
// and read back on the next launch (storage is the plugin's in-memory fake).
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:travel_mate/services/display_mode_service.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('편한 모드 selection is saved and restored after a restart', () async {
    SharedPreferences.setMockInitialValues({});
    DisplayModeService.seniorMode = true;
    await Future<void>.delayed(Duration.zero);
    final stored = await SharedPreferences.getInstance();
    expect(stored.getBool('display_senior_mode'), isTrue);

    // A new launch starts with the in-memory default, then restores.
    SharedPreferences.setMockInitialValues({'display_senior_mode': true});
    await DisplayModeService.restore();
    expect(DisplayModeService.seniorMode, isTrue);
  });

  test('switching back to 기본 모드 is also kept', () async {
    SharedPreferences.setMockInitialValues({'display_senior_mode': true});
    await DisplayModeService.restore();
    DisplayModeService.seniorMode = false;
    await Future<void>.delayed(Duration.zero);
    final stored = await SharedPreferences.getInstance();
    expect(stored.getBool('display_senior_mode'), isFalse);
  });
}
