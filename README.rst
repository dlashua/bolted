BOLTED
######

Under Development
*****************

Bolted is still under heavy development and should be considered *alpha* code. Features may be broken, documentation may be inaccurate, and there is no guarantee that the API won't change from commit to commit.

Bug Reports, Feature Requests, and Pull Requests are high encouraged.

What is Bolted?
***************

Bolted aims to make developing complex `Home Assistant <https://home-assistant.io/>`_ automations easier and to add some quality of life improvements for developing integrations (i.e. custom components).

It is, itself, a ``custom component`` within Home Assistant. But, unlike most custom components which provide a specific feature, device integration, or perform a specific task, **Bolted** is a Framework doing the things an Integration would normally do. It is a Home Assistant Integration Framework that provides a better, friendlier developer experience than Custom Components alone. It makes development so easy, in fact, that it can be used to accomplish things that would normally be considered too "small" for a full-blown Integration, or things that would be considered too "complex" for Automations and Scripts alone.


Why Bolted?
***********

For complex automations, Home Assistant certainly already includes a rich feature set to accomotate the needs of most automations. Some of these are available through a Web Based UI, while even more complex automations can be created using YAML Automation Syntax. In order to acheieve this, Home Assistant has effectively created a domain specific, YAML based programming language, also known as `Scripts <https://www.home-assistant.io/docs/scripts>`_. These are available standalone, or in the ``action`` section of automations.

However, this means that not every language feature you may be accustomed to using is available. Additionally, you may not prefer the YAML syntax over a more conventional programming language. Thankfully, Home Assistant is writen in Python.

**Bolted** allows you to write Automations and Integrations in Python. Of course, this is already possible using Home Assistant ``custom components``. Bolted improves this experience by providing easy access to the various pieces of Home Assistant's infrastructure in one, simple to use, class that your automation extends. Additionally, it provides hot reloading of these classes to end the "code, save, restart Home Assistant" cycle. Finally, it promotes reusability by allowing multiple instances of these classes to be configured via YAML.

Why NOT an Integration/Custom Component?
========================================

**Bolted** itself is an Integration / Custom Component, which, in turn, provides a Framework for creating Integration/Automation-like behavior.

The overhead required for writing an Integration is large. Too large, in many cases, to justify writing one for an Automation when YAML Script Syntax can likely get you where you need to be, even if it ends up overly complicated and/or difficult to read. 

**Bolted** removes nearly all of the boilerplate required, and most of the complexity surrounding the Integration and allows you to focus on just the meat of what you're trying to do.

Additionally, Automations can be tricky, with edge cases that aren't always obvious until you're well into development. If you have devices to spare, you can run a development instance of Home Assistant with those devices in it and restart Home Assistant every time you adjust the code. However, if you don't have devices to spare, **Bolted** can reload *just* the affected code, allowing you to develop the code alongside your devices in a single Home Assistant Instance without taking everything down for each restart.

If you're developing a True Integration that interacts with an external API to provide State and Entities to Home Assistant (as opposed to an advanced, reusable Automation), **Bolted** can still help by removing the boilerplate code required and provide hot reloading of your code. If you do something terribly wrong, a restart may still be required to clean up your mess, but it is needed far less often and only when dealing with turn up and tear down of remote connections.

Quick Documentation
*******************

In place of actual documentation until the API stabilizes, this should help get you started with **Bolted**:

1. Install this **Bolted** custom component in the usual way.
2. Create a directory in your Home Assistant config directory called ``bolted``, and in that create a directories called ``apps``, ``modules``, and ``config``.
3. Place this in your ``configuration.yaml``:

    .. code:: yaml

        bolted: !include bolted/config/config.yaml

4. Create an Empty File at ``bolted/config/config.yaml``
5. Restart Home Assistant
6. Create Python Code in a ``whateveryouwant.py`` file in the ``apps`` directory like this:

    .. code:: python

        from custom_components.bolted.types import BoltedApp
        class App(BoltedApp):
            def startup(self):
                do_something_here()
                self.logger.info(self.config)
            
7. The Class Name must be ``App``. The ``startup`` method will be called automatically by **Bolted** to start your app.
8. Register an Instance of this App in ``bolted\config\config.yaml``:

    .. code:: yaml

        apps:
          - name: my_app_instance
            # use the file name you created above without the extension
            app: whateveryouwant
            more: config
            stuff: goes
            here:
              nested: however
              you: want

9.  **Bolted** will automatically recognize the new App and App Instance Configuration and start the App Instance.
10. Change the code or config and save, and **Bolted** will restart whatever needs to be restarted.

Look at the `BoltedBase Class <https://github.com/dlashua/bolted/blob/main/custom_components/bolted/types.py#L122>`_ to see what methods are available to you inside your apps.

Feature Roadmap
***************

1. Script Sequence Support
    * Single Bolted Method supporting Full Home Assistant YAML Script Syntax
2. Home Assistant Device Support
    * Create Devices with Multiple Entities 
3. Integration Support 
    * Let specific **Bolted** apps run under a different domain
4. Export as Custom Component
    * Command to export an app as a separate, fully functional custom-component
5. Config Flow support for Bolted Setup and App Configuration


But this already exists!
************************

Applications and Custom Components with features similar to **Bolted** already exist.

* Node Red along with the `Node Red Component <https://flows.nodered.org/node/node-red-contrib-home-assistant-websocket>`_
* `AppDaemon <https://github.com/AppDaemon/appdaemon>`_
* `Pyscript <https://github.com/custom-components/pyscript>`_
* `NetDaemon <https://github.com/net-daemon/netdaemon>`_

If these packages suit your needs, then that's great. **Bolted**, however, intends to improve upon that experience. It borrows ideas and APIs from several of these packages with the intent of producing the best developer and user experience.

Why NOT AppDaemon?
==================

AppDaemon lives outside of Home Assistant. This design has some positive aspects. Primarily, if something goes wrong in AppDaemon or an AppDaemon App, it is unlikely to crash all of Home Assistant. However, this comes at some cost. 

Because AppDaemon lives outside of Home Assistant, there are some features that are not available to it. AppDaemon can only do what Home Assistant's websocket connection allows. So you can, for instance, set a state in Home Assistant. However, you cannot create a true Home Assistant entity. For things like a ``binary_sensor``, this doesn't mean much in the end. You can't change the entity_id in the UI of an entity created like this, but you can change the entity ID in the App's code or in the App Instance's YAML, if the App is written that way. However, for ``switch`` entities, for instance, there is no mechanism available to respond to a ``switch.turn_on`` service call. So, creating a working ``switch`` entity through AppDaemon can only be done through an awkward use of MQTT that isn't catered to out-of-the-box. The same goes for any entity type that can accept service calls (``climate``, ``light``, ``media_player``, etc).

**Bolted** lives inside Home Assistant. Entity creation is built into **Bolted**. When Entities are created, every feature available to standard Home Assistant Components are available within **Bolted** as well.

AppDaemon keeps a record of all Home Assistant state, internally. This means that when an Entity State changes in Home Assistant, this must be communicated over the websocket connection to AppDaemon. Then AppDaemon stores that state. Finally, it notifies your AppDaemon App of the changed state and the actual App Code takes over. While the entire process takes milliseconds, it's added complexity and memory that isn't absolutely needed.

**Bolted** uses the Home Assistant state machine. It hooks into Home Assistant using the same mechanisms that Automations and other Integrations use. It doesn't require a copy (AppDaemon's internal state) of a copy (from the websocket) of Home Assistant State Notifications.

AppDaemon requires you to run a separate process. For some, this is an advantage. However, in many cases, it's just one more service to keep running and/or check on when something goes wrong.

**Bolted** is inside Home Assistant. When you restart Home Assistant, **Bolted** is restarted too.

Why NOT PyScript?
=================

PyScript is not actually Python. It uses a AST Parser to read your python-like code and perform the actions you intended. This provides a lot of truly, nice things. For instance, in PyScript the variable `input_boolean.test_1` will have the value of the state of that entity in Home Assistant. You don't have to set anything special or do anything special, it just is. You can write --

.. code:: python

    if input_boolean.test_1 == 'on':
      do_this_thing()

-- and it works just like you'd expect. There are many, many more features like this in PyScript that make reading and writing automations simple. However, pull that code into a regular IDE (like VSCode for instance) and it's confused, with warnings and errors everywhere because, as I said before, it's not actually Python. Many of the variables, functions, and decorators you use with PyScript don't actually exist as real Python constructs.

If you get too deep into the Python you need to write your automation, you'll find that some of the Python language features have not been implemented, or are implemented differently. A common decorator to use in PyScript is ``@state_trigger``. However, this is not a *real* decorator. You can't use it like ``state_trigger(whatever, some_function_name_here)`` and expect it to behave like a real decorator would.

Additionally, despite PyScript being *in* Home Assistant, it doesn't have top level support for Entity creation. And, because of the way Platform Entities work in Home Assistant, despite having access to the Home Assstant Object in PyScript (for Advanced Use Cases) real Platform Entities can't be created without modifications to the PyScript source to provide all of the boilerplate Home Assistant requires for this to work.

**Bolted** is real Python. Each "Application" you write is just a class. Your class extends a provided **Bolted** Class -- the same way AppDaemon works -- which gives you access to the features **Bolted** provides. If you need other Classes or Modules to get the job done, you can do so in the regular Python way. This means you'll be using lots of method calls and you're going to see the variable ``self`` a lot. If you're using ``async`` methods you also need to use ``await``, because it's real Python. PyScript hides all of this from the user making the language quite simple and beautiful, but, also lacking if you dig too far under the surface.

Why NOT Node-Red?
=================

Node-RED is UI based. While this works for some people, others prefer a more code-based approach to automation development. If you enjoy the UI aspects of Node-RED, the ecosystem provided by the Node-RED Custom Component is very capable.


Why NOT NetDaemon?
==================

To be honest, I've never used it as I don't prefer writing in C#. However, based on what I do know, NetDaemon will have the same Pros and Cons as AppDaemon, but with C# as the programming langugage in use. 

