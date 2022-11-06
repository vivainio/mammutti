from distutils.core import setup

setup(name='mammutti',
      version='1.0.0',
      description='Analyze huge .NET source trees for common errors',
      author='Ville M. Vainio',
      author_email='vivainio@gmail.com',
      url='https://github.com/vivainio/mammutti',
      packages=['mammutti'],
      install_requires=["pydantic"],
      entry_points = {
        'console_scripts': [
            'mammutti = mammutti.mammutti:main'
        ]
      }
     )
