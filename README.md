# mammutti

Problem: you have a big "enterprise grade" project with lots of solutions, with even more subprojects.

This command line application was written to analyze integrity of large .NET applications. It produces a 
human-readable YAML dump of all  modules (csprojs) in the repository, and checks whether dependencies are correctly declared. 
The yaml contains "errors" for problems it finds.

The yaml can also be read in your own scripts to do custom analysis, e.g. "what happens when I delete this module".
Or, you can diff the yaml files across different points in time to see what changes in global dependency picture.

Installation: 

```commandline
$ pip install mammutti

```

Usage:

```commandline
$ mammutti c:\my\big\project > my_analysis.yaml
```


