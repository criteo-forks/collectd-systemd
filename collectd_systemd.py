import dbus
import collectd
import re

SERVICE_SUFFIX = '.service'

class SystemD(object):
    def __init__(self):
        self.plugin_name = 'systemd'
        self.interval = 60.0
        self.verbose_logging = False
        self.services = []
        self.units = {}

    def log_verbose(self, msg):
        if not self.verbose_logging:
            return
        collectd.info('{} plugin [verbose]: {}'.format(self.plugin_name, msg))

    def init_dbus(self):
        self.bus = dbus.SystemBus()
        self.manager = dbus.Interface(self.bus.get_object('org.freedesktop.systemd1',
                                                          '/org/freedesktop/systemd1'),
                                      'org.freedesktop.systemd1.Manager')

    def get_unit(self, name):
        if name not in self.units:
            try:
                unit = dbus.Interface(self.bus.get_object('org.freedesktop.systemd1',
                                                          self.manager.GetUnit(name)),
                                      'org.freedesktop.DBus.Properties')
            except dbus.exceptions.DBusException as e:
                collectd.warning('{} plugin: failed to monitor unit {}: {}'.format(
                    self.plugin_name, name, e))
                return
            self.units[name] = unit
        return self.units[name]

    def get_service_state(self, name):
        unit = self.get_unit(name)
        if not unit:
            return 'broken'
        else:
            return unit.Get('org.freedesktop.systemd1.Unit', 'SubState')

    def get_service_type(self, name):
        unit = self.get_unit(name)
        if not unit:
            return 'broken'
        else:
            return unit.Get('org.freedesktop.systemd1.Service', 'Type')

    def get_service_status_code(self, name):
        unit = self.get_unit(name)
        if not unit:
            return 'broken'
        else:
            return unit.Get('org.freedesktop.systemd1.Service', 'ExecMainStatus')

    def service_is_running(self, name):
        state = self.get_service_state(name)
        type = self.get_service_type(name)
        status_code = self.get_service_status_code(name)
        if state == 'running':
            return 1
        if type == 'oneshot' and status_code == 0:
            return 1
        return 0

    def configure_callback(self, conf):
        for node in conf.children:
            vals = [str(v) for v in node.values]
            if node.key == 'Service':
                self.services = vals
            elif node.key == 'Interval':
                self.interval = float(vals[0])
            elif node.key == 'Verbose':
                self.verbose_logging = (vals[0].lower() == 'true')
            else:
                raise ValueError('{} plugin: Unknown config key: {}'
                                 .format(self.plugin_name, node.key))
        if not self.services:
            self.log_verbose('No services defined in configuration')
            return
        self.init_dbus()
        services = []
        for pattern in self.services:
            for unit in self.manager.ListUnits():
                if re.search('^%s\%s$' %(pattern, SERVICE_SUFFIX), unit[0]):
                    services.append(re.sub('\%s$' % (SERVICE_SUFFIX), '', unit[0]))
        self.services = services
        collectd.register_read(self.read_callback, self.interval)
        self.log_verbose('Configured with services={}, interval={}'
                         .format(self.services, self.interval))

    def read_callback(self):
        self.log_verbose('Read callback called')
        for name in self.services:
            full_name = name + SERVICE_SUFFIX
            value = float(self.service_is_running(full_name))
            self.log_verbose('Sending value: {}.{}={}'
                             .format(self.plugin_name, name, value))
            val = collectd.Values(
                type='gauge',
                plugin=self.plugin_name,
                plugin_instance=name,
                type_instance='running',
                values=[value])
            val.dispatch()


mon = SystemD()
collectd.register_config(mon.configure_callback)
