import mock
import pytest
import dbus
import collectd_systemd


@pytest.fixture
def conf_bare():
    return mock.Mock(children=[
        mock.Mock(key='Interval', values=[120.0]),
    ])


@pytest.fixture
def conf_valid(conf_bare):
    conf_bare.children.extend([
        mock.Mock(key='Verbose', values=['true']),
        mock.Mock(key='Service', values=['service1', '.*foo']),
    ])
    return conf_bare


@pytest.fixture
def conf_invalid(conf_bare):
    conf_bare.children.append(mock.Mock(key='Foo', values=[1]))
    return conf_bare


@pytest.fixture
def mon():
    return collectd_systemd.SystemD()


@pytest.fixture
def configured_mon(mon, conf_valid):
    with mock.patch('dbus.Interface') as m:
        i = m.return_value
        i.ListUnits.return_value = [['service1.service', 'foo'], ['service2foo.service', 'bar']]
        mon.configure_callback(conf_valid)
        return mon


def test_configure(mon, conf_valid):
    with mock.patch('collectd.register_read') as m:
        with mock.patch('dbus.Interface') as l:
            i = l.return_value
            i.ListUnits.return_value = [['service1.service', 'foo'], ['service2foo.service', 'bar']]
            mon.configure_callback(conf_valid)
            m.assert_called_once_with(mon.read_callback, mock.ANY)
    assert hasattr(mon, 'bus')
    assert hasattr(mon, 'manager')
    assert mon.interval == 120.0
    assert mon.verbose_logging
    assert len(mon.services) == 2


def test_configure_does_nothing_if_no_services(mon, conf_bare):
    with mock.patch.object(mon, 'init_dbus') as m:
        mon.configure_callback(conf_bare)
        m.assert_not_called()
    assert not mon.verbose_logging


def test_configure_invalid_setting(mon, conf_invalid):
    with pytest.raises(ValueError):
        mon.configure_callback(conf_invalid)


def test_get_unit(configured_mon):
    u = configured_mon.get_unit('foo')
    assert u is not None
    with mock.patch('dbus.Interface', side_effect=dbus.exceptions.DBusException):
        u = configured_mon.get_unit('missing')
        assert u is None


def test_get_service_state(configured_mon):
    with mock.patch.object(configured_mon, 'get_unit') as m:
        m().Get.return_value = 'running'
        state = configured_mon.get_service_state('foo')
        assert state == 'running'
    with mock.patch('dbus.Interface', side_effect=dbus.exceptions.DBusException):
        state = configured_mon.get_service_state('missing')
        assert state == 'broken'

def test_service_is_running(configured_mon):
    with mock.patch.object(configured_mon, 'get_service_state', return_value='running'):
        state = configured_mon.service_is_running('foo')
        assert state == 1
    with mock.patch.object(configured_mon, 'get_service_state', return_value='failing'):
        state = configured_mon.service_is_running('foo')
        assert state == 0
    with mock.patch.object(configured_mon, 'get_service_state', return_value='dead'):
        with mock.patch.object(configured_mon, 'get_service_type', return_value='oneshot'):
            with mock.patch.object(configured_mon, 'get_service_status_code', return_value=1):
                state = configured_mon.service_is_running('foo')
                assert state == 0
    with mock.patch.object(configured_mon, 'get_service_state', return_value='dead'):
        with mock.patch.object(configured_mon, 'get_service_type', return_value='oneshot'):
            with mock.patch.object(configured_mon, 'get_service_status_code', return_value=0):
                state = configured_mon.service_is_running('foo')
                assert state == 1

def test_send_metrics(configured_mon):
    with mock.patch.object(configured_mon, 'get_service_state') as m:
        m.side_effect = ['running', 'failed']
        with mock.patch('collectd.Values') as val_mock:
            configured_mon.read_callback()
            assert val_mock.call_count == 2
            c1_kwargs = val_mock.call_args_list[0][1]
            assert c1_kwargs['plugin_instance'] == 'service1'
            assert c1_kwargs['values'] == [1]
            c2_kwargs = val_mock.call_args_list[1][1]
            assert c2_kwargs['plugin_instance'] == 'service2foo'
            assert c2_kwargs['values'] == [0]
